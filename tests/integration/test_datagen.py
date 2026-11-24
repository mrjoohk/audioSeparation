"""W200000 requirements REQ-201..206 on synthetic stand-in assets."""
import json
import os
import time

import numpy as np
import pytest
from scipy.io import wavfile

from datagen.assets import build_synthetic_library
from datagen.planner import (
    ScenarioPrior,
    check_plan_constraints,
    duplicate_rate,
    make_room_catalog,
    sample_scenarios,
    split_pools,
)
from datagen.publish import (
    ReleaseError,
    deficient_bins,
    generate_dataset,
    publish_release,
    qc_gate,
    supplement_plans,
    tier_overlap_report,
    verify_release,
)
from datatools.loader import load_scene
from datatools.splits import check_split_leakage
from datatools.vad import boundary_f1, segments_to_mask, shift_segments, vad_segments

RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    return build_synthetic_library(str(tmp_path_factory.mktemp("assets")), n_speakers=20,
                                   utts_per_speaker=3, n_noises=8, utt_s=3.0, seed=4)


@pytest.fixture(scope="module")
def world(lib):
    prior = ScenarioPrior(duration_s=4.0, ism_order=1, storage_profile="full",
                          room_L=(4.0, 8.0), room_W=(3.5, 6.0), n_room_templates=30)
    rooms = make_room_catalog(prior, seed=2)
    pools = split_pools(lib, rooms, RATIOS, seed=3)
    return prior, rooms, pools


def test_req201_sampling_speed_constraints_duplicates(lib):
    prior = ScenarioPrior(room_L=(3.0, 10.0), n_speakers=(1, 4))
    rooms = make_room_catalog(prior)
    pools = split_pools(lib, rooms, RATIOS)
    t0 = time.perf_counter()
    plans = sample_scenarios(prior, 10_000, lib, pools, rooms, "train", seed=1)
    assert time.perf_counter() - t0 < 10.0
    assert check_plan_constraints(plans, prior) == []
    assert duplicate_rate(plans) < 0.001


def test_calibration_stratified_assignment_renders_each_target_once(world, lib):
    from dataclasses import replace
    prior, rooms, pools = world
    targets = [0.2, 0.3, 0.45, 0.6, 0.8]
    strat = replace(prior, calibration={"id": "c", "rt60_samples": targets, "assignment": "stratified"})
    got = [p["plan"]["target_rt60_s"] for p in sample_scenarios(strat, 10, lib, pools, rooms, "train", seed=3)]
    assert sorted(got) == sorted(targets * 2)
    rand = replace(prior, calibration={"id": "c", "rt60_samples": targets})
    got_r = [p["plan"]["target_rt60_s"] for p in sample_scenarios(rand, 10, lib, pools, rooms, "train", seed=3)]
    assert set(got_r) <= set(targets)


def test_req203_tier_overlap_planned(world, lib):
    prior, rooms, pools = world
    for tier, target in prior.tiers.items():
        plans = sample_scenarios(prior, 300, lib, pools, rooms, "train", seed=7, tier=tier)
        any_ = sum(p["plan"]["planned_any_frames"] for p in plans)
        multi = sum(p["plan"]["planned_multi_frames"] for p in plans)
        assert abs(multi / any_ - target) < 0.05, (tier, multi / any_)


def test_req206_asset_pools_have_no_leakage(tmp_path):
    big = build_synthetic_library(str(tmp_path), n_speakers=100, utts_per_speaker=1,
                                  n_noises=50, utt_s=0.5, seed=9)
    prior = ScenarioPrior()
    pools = split_pools(big, make_room_catalog(prior), RATIOS, seed=0)
    items = []
    for sp, p in pools.items():
        for aid in p["speech"] + p["noise"]:
            items.append({"id": aid, "split": sp, "keys": big.assets[aid].keys})
        for rid in p["rooms"]:
            items.append({"id": rid, "split": sp, "keys": {"room": rid}})
    assert check_split_leakage(items, ("speaker", "noise", "room")) == []
    n_spk = {sp: len({big.assets[a].keys["speaker"] for a in p["speech"]}) for sp, p in pools.items()}
    assert n_spk == {"train": 80, "val": 10, "test": 10}


def _render_plans(world, lib, out, n, tier=None, seed=11, split="train"):
    prior, rooms, pools = world
    plans = sample_scenarios(prior, n, lib, pools, rooms, split, seed=seed, output_dir=str(out), tier=tier)
    s = generate_dataset(plans, str(out), workers=1)
    assert s.n_failed == 0, s.failure_reasons
    return plans


def test_req202_snr_within_1db(world, lib, tmp_path):
    prior, rooms, pools = world
    plans = sample_scenarios(prior, 4, lib, pools, rooms, "train", seed=21, output_dir=str(tmp_path))
    for p, snr in zip(plans, (0.0, 5.0, 10.0, 15.0)):
        if p["plan"]["noise_id"] is None:
            continue
        p["config"]["mix"] = {"target_snr_db": snr}
    generate_dataset(plans, str(tmp_path))
    checked = 0
    for p in plans:
        if p["plan"]["noise_id"] is None:
            continue
        b = load_scene(os.path.join(tmp_path, p["config"]["scene_id"], "scene_manifest.json"))
        roles = b.manifest["labels"]["roles"]
        r = b.reference_channel
        sp = sum(b.references[i, r] for i, s in enumerate(b.source_ids) if roles[s] == "speech")
        nz = sum(b.references[i, r] for i, s in enumerate(b.source_ids) if roles[s] == "noise")
        win = np.zeros(sp.shape, bool)
        for s, segs in b.manifest["labels"]["vad"].items():
            if roles[s] == "speech":
                win |= segments_to_mask(segs, len(win))
        snr = 10 * np.log10(np.mean(sp[win] ** 2) / np.mean(nz[win] ** 2))
        assert abs(snr - p["config"]["mix"]["target_snr_db"]) <= 1.0
        checked += 1
    assert checked >= 1


def test_req204_vad_label_sync(world, lib, tmp_path):
    """Manifest VAD vs VAD of the clean dry stem (shifted by the direct delay):
    F1 > 0.999 outside a ±1 ms (16-sample) boundary margin."""
    plans = _render_plans(world, lib, tmp_path, 3, tier="medium", seed=31)
    for p in plans:
        sid = p["config"]["scene_id"]
        b = load_scene(os.path.join(tmp_path, sid, "scene_manifest.json"))
        m = b.manifest
        T = m["render"]["n_samples"]
        pairs = {(q["source_id"], q["receiver_id"]): q for q in m["geometry"]["pairs"]}
        ref = m["render"]["reference_receiver"]
        for s in b.source_ids:
            if m["labels"]["roles"][s] != "speech":
                continue
            fs, dry = wavfile.read(os.path.join(tmp_path, sid, f"dry__{s}.wav"))
            truth = segments_to_mask(shift_segments(vad_segments(dry, fs),
                                                    pairs[(s, ref)]["direct_delay_samples"], T), T)
            pred = segments_to_mask(m["labels"]["vad"][s], T)
            assert boundary_f1(pred, truth, tol=16) > 0.999


def test_req203_rendered_overlap_matches_tiers(world, lib, tmp_path):
    """Cumulative VAD overlap of *rendered* scenes per tier stays near the target
    (REQ-203 asks ±5 % over 1,000 scenes; 4 short scenes per tier → ±8 %)."""
    prior = world[0]
    for k, tier in enumerate(prior.tiers):
        out = tmp_path / tier
        plans = _render_plans(world, lib, out, 4, tier=tier, seed=40 + k)
        acc, rej = qc_gate(str(out), plans)
        assert not rej, rej
        r = tier_overlap_report(acc)[tier]
        assert abs(r["cumulative_overlap"] - r["target"]) < 0.08, (tier, r)


def test_req205_qc_release_and_supplement(world, lib, tmp_path):
    prior, rooms, pools = world
    plans = sample_scenarios(prior, 20, lib, pools, rooms, "train", seed=51, output_dir=str(tmp_path))
    plans += sample_scenarios(prior, 4, lib, pools, rooms, "val", seed=52, output_dir=str(tmp_path))
    plans[3]["config"]["receivers"][0]["gain_db"] = 30.0     # force clipping in 1 of 24 scenes
    plans[3]["config"]["receivers"][0]["clip_threshold_dbfs"] = 0.0
    generate_dataset(plans, str(tmp_path))
    acc, rej = qc_gate(str(tmp_path), plans)
    assert [r["scene_id"] for r in rej if r["reason"] == "clipping"] == [plans[3]["config"]["scene_id"]]
    rel = publish_release(str(tmp_path), acc, rej, "synthmeet", "0.1.0", shard_size=8)
    ok, bad = verify_release(rel)
    assert ok, bad
    rep = json.load(open(os.path.join(rel, "qc_report.json"), encoding="utf-8"))
    assert rep["clipped_in_release"] == 0 and rep["rejected_by_reason"]["clipping"] == 1
    assert rep["leakage"] == []
    idx = json.load(open(os.path.join(rel, "index.json"), encoding="utf-8"))
    assert {e["split"] for e in idx["scenes"]} == {"train", "val"}
    with pytest.raises(ReleaseError):
        publish_release(str(tmp_path), acc, rej, "synthmeet", "0.1.0")
    shard = os.path.join(rel, idx["scenes"][0]["shard"])
    with open(shard, "ab") as fh:
        fh.write(b"tamper")
    assert not verify_release(rel)[0]
    # rare-condition top-up: demand 8 'hard' scenes
    deficits = deficient_bins(acc, lambda e: e["tier"], ["hard"], min_count=8)
    if deficits:
        extra = supplement_plans(prior, deficits, lib, pools, rooms, "train", seed=60, output_dir=str(tmp_path))
        assert len(extra) == deficits["hard"] and all(p["plan"]["tier"] == "hard" for p in extra)


def test_events_injected_as_interference(world, lib, tmp_path):
    from dataclasses import replace
    prior, rooms, pools = world
    p2 = replace(prior, event_prob=1.0)
    plans = sample_scenarios(p2, 3, lib, pools, rooms, "train", seed=71, output_dir=str(tmp_path))
    assert all(p["plan"]["event_ids"] for p in plans)
    generate_dataset(plans, str(tmp_path))
    acc, rej = qc_gate(str(tmp_path), plans)
    assert not rej
    for p in plans:
        m = json.load(open(os.path.join(tmp_path, p["config"]["scene_id"], "scene_manifest.json"), encoding="utf-8"))
        assert "interference" in m["labels"]["roles"].values()
    events = {sp: set(pp["event"]) for sp, pp in pools.items()}
    assert not (events["train"] & events["val"]) and not (events["train"] & events["test"])
