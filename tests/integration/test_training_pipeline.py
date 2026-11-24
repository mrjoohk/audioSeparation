"""Stage 5: release → training (deterministic, versioned) → system comparison."""
import json
import os

import numpy as np
import pytest

from datagen.assets import build_synthetic_library
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools
from datagen.publish import generate_dataset, publish_release, qc_gate
from datatools.loader import load_scene
from evaluation.compare import evaluate_systems
from training.dsp import srp_phat, stft_c
from training.models import RidgeMaskModel
from training.systems import DelaySumBaseline, MaskCandidate, Unprocessed, mic_positions
from training.train import release_scenes, train_from_release


@pytest.fixture(scope="module")
def release(tmp_path_factory):
    root = tmp_path_factory.mktemp("e2e")
    lib = build_synthetic_library(str(root / "assets"), n_speakers=12, utts_per_speaker=2,
                                  n_noises=4, utt_s=2.0, seed=1)
    prior = ScenarioPrior(arrays=("circular4",), duration_s=2.5, ism_order=1, n_speakers=(2, 2),
                          tiers={"medium": 0.2}, tier_weights={"medium": 1}, noise_prob=0.0,
                          storage_profile="training", n_room_templates=12)
    rooms = make_room_catalog(prior, seed=1)
    pools = split_pools(lib, rooms, {"train": 0.75, "test": 0.25}, seed=1)
    render = str(root / "render")
    plans = sample_scenarios(prior, 10, lib, pools, rooms, "train", seed=2, output_dir=render)
    plans += sample_scenarios(prior, 3, lib, pools, rooms, "test", seed=3, output_dir=render)
    generate_dataset(plans, render)
    acc, rej = qc_gate(render, plans)
    assert not rej, rej
    return publish_release(render, acc, rej, "t", "1.0.0"), render, root


def test_training_is_deterministic_and_versioned(release):
    rel, render, root = release
    e1 = train_from_release(rel, render, str(root / "run1"), seed=0)
    e2 = train_from_release(rel, render, str(root / "run2"), seed=0)
    assert e1["checkpoint"]["sha256"] == e2["checkpoint"]["sha256"]
    assert e1["data"]["release_manifest_sha256"] and e1["data"]["split"] == "train"
    assert e1["data"]["n_scenes"] == 10 and e1["code"]["commit"] is not None
    on_disk = json.load(open(root / "run1" / "experiment.json", encoding="utf-8"))
    assert on_disk["checkpoint"] == e1["checkpoint"]


def test_training_refuses_wrong_data_version(release):
    rel, render, root = release
    scenes = release_scenes(rel, render, "train")
    bad = [(scenes[0][0], "0" * 64)]
    from datatools.loader import SceneContractError
    from training.train import train_mask_model
    with pytest.raises(SceneContractError):
        train_mask_model(bad, str(root / "bad"))


def test_srp_phat_clean_scene(release):
    rel, render, _ = release
    errs = []
    for mpath, fp in release_scenes(rel, render, "test"):
        b = load_scene(mpath)
        ref = b.reference_channel
        est = srp_phat(stft_c(b.mixture.astype(float), b.fs), b.fs, mic_positions(b), ref, 2)
        for p in b.manifest["geometry"]["pairs"]:
            if p["receiver_id"] == b.receiver_ids[ref]:
                t = p["doa_az_deg"] % 360
                errs.append(min(min(abs(e - t) % 360, 360 - abs(e - t) % 360) for e in est))
    assert np.median(errs) < 20.0


def test_compare_report(release):
    rel, render, root = release
    train_from_release(rel, render, str(root / "run"), seed=0)
    model = RidgeMaskModel.load(str(root / "run" / "mask_model.npz"))
    rep = evaluate_systems(release_scenes(rel, render, "test"),
                           [Unprocessed(), DelaySumBaseline(), MaskCandidate(model)],
                           candidate="candidate_mask", references=["unprocessed", "baseline_ds"],
                           out_dir=str(root / "eval"))
    s = rep["summary"]
    assert s["n_scenes"] == 3
    assert s["means"]["unprocessed"]["si_sdri_db"] == pytest.approx(0.0, abs=1e-9)
    assert "candidate_mask-vs-baseline_ds:si_sdri_db" in s["paired"]
    assert os.path.exists(root / "eval" / "comparison.md")
