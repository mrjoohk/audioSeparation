"""Stage 8: locked benchmarks (REQ-403), ablation dashboard (REQ-404), release gate (REQ-405),
tracking metrics (W414 / proposed REQ-406)."""
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

from datagen.assets import build_synthetic_library
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools
from datagen.publish import generate_dataset, publish_release, qc_gate
from datatools.loader import load_scene
from datatools.splits import BenchmarkIntegrityError
from evaluation.ablation import attribution, write_dashboard
from evaluation.benchmark import load_benchmark, lock_benchmark
from evaluation.gate import decide, load_rules, report_markdown
from evaluation.localization import tracking_metrics, track_azimuths, truth_tracks

ROOT = Path(__file__).parents[2]


@pytest.fixture(scope="module")
def rel(tmp_path_factory):
    root = tmp_path_factory.mktemp("bench")
    lib = build_synthetic_library(str(root / "assets"), n_speakers=8, utts_per_speaker=2, n_noises=2,
                                  n_events=2, utt_s=1.5, seed=2)
    prior = ScenarioPrior(arrays=("pair10",), duration_s=2.0, ism_order=1, n_speakers=(1, 2),
                          n_room_templates=8, storage_profile="training", event_prob=0.0)
    rooms = make_room_catalog(prior, seed=1)
    pools = split_pools(lib, rooms, {"train": 0.5, "test": 0.5}, seed=1)
    render = str(root / "render")
    plans = sample_scenarios(prior, 3, lib, pools, rooms, "test", seed=5, output_dir=render)
    generate_dataset(plans, render)
    acc, rej = qc_gate(render, plans)
    return publish_release(render, acc, rej, "bench-src", "1.2.0"), root


# --- REQ-403 -----------------------------------------------------------------------

def test_benchmark_identical_on_three_servers(rel, tmp_path):
    release, _ = rel
    spec = tmp_path / "bench_v1.2.yaml"
    lock_benchmark(release, "test", "synthmeet-bench", "1.2", str(spec), str(tmp_path / "cache0"))
    hashes = set()
    for k in range(3):                       # three independent caches / copies of the release
        copy = tmp_path / f"server{k}" / "release"
        shutil.copytree(release, copy)
        out = load_benchmark(str(spec), str(copy), str(tmp_path / f"server{k}" / "cache"))
        hashes.add(out["data_sha256"])
        assert [Path(m).parent.name for m, _ in out["scenes"]] == sorted(Path(m).parent.name for m, _ in out["scenes"])
    assert len(hashes) == 1


def test_benchmark_detects_wrong_version_and_missing_shard(rel, tmp_path):
    release, _ = rel
    spec = tmp_path / "b.yaml"
    lock_benchmark(release, "test", "b", "1.0", str(spec), str(tmp_path / "c0"))
    import yaml
    s = yaml.safe_load(open(spec, encoding="utf-8"))
    s["release"]["release_manifest_sha256"] = "0" * 64       # all servers read the same wrong version
    bad = tmp_path / "bad.yaml"
    yaml.safe_dump(s, open(bad, "w", encoding="utf-8"))
    with pytest.raises(BenchmarkIntegrityError):
        load_benchmark(str(bad), release, str(tmp_path / "c1"))
    copy = tmp_path / "r2"
    shutil.copytree(release, copy)
    shard = next((copy / "shards").iterdir())
    shard.unlink()
    with pytest.raises(BenchmarkIntegrityError):
        load_benchmark(str(spec), str(copy), str(tmp_path / "c2"))


# --- REQ-405 -----------------------------------------------------------------------

def _sessions(n, base_wer, cand_delta, unproc=0.4, cond_of=lambda i: "meeting"):
    rng = np.random.default_rng(0)
    out, cond = {}, {}
    for i in range(n):
        b = base_wer + rng.normal(0, 0.002)
        out[f"s{i}"] = {"fixed_baseline": {"wer": b, "cpwer": b}, "candidate": {"wer": b + cand_delta, "cpwer": b + cand_delta},
                        "unprocessed": {"wer": unproc, "cpwer": unproc}}
        cond[f"s{i}"] = cond_of(i)
    return out, cond


def test_gate_blocks_half_percent_wer_regression(tmp_path):
    rules = load_rules(str(ROOT / "configs" / "decision_rules.yaml"))
    sessions, cond = _sessions(30, 0.20, +0.005)              # 0.5 % worse than the fixed baseline
    d = decide(rules, sessions, "candidate", cond)
    assert d["verdict"] == "fail" and d["regression"]["verdict"] == "fail"
    assert d["advisory"] is False                             # rules approved 2026-11-23
    assert decide({**rules, "status": "proposed"}, sessions, "candidate", cond)["advisory"] is True
    md = report_markdown(d)
    assert "FAIL" in md and "regression" in md.lower()


def test_gate_passes_clear_improvement_and_flags_small_sample():
    rules = load_rules(str(ROOT / "configs" / "decision_rules.yaml"))
    assert {r["metric"] for r in rules["comparisons"] if r["id"].startswith("wer_vs")} == {"cpwer"}   # 2026-11-24 amendment
    rules["comparisons"] = [r for r in rules["comparisons"] if r["id"].startswith("wer_vs")]
    sessions, cond = _sessions(30, 0.20, -0.04)
    assert decide(rules, sessions, "candidate", cond)["verdict"] == "pass"
    few, cond = _sessions(5, 0.20, -0.04)
    assert decide(rules, few, "candidate", cond)["verdict"] == "inconclusive"


def test_gate_zero_reference_rule():
    rules = {"comparisons": [{"id": "z", "metric": "wer", "reference": "fixed_baseline", "kind": "absolute_pp",
                              "max_change": -3.0, "zero_reference": "candidate_must_be_zero"}]}
    s = {"a": {"fixed_baseline": {"wer": 0.0}, "candidate": {"wer": 0.0}}}
    assert decide(rules, s, "candidate")["verdict"] == "pass"
    s["a"]["candidate"]["wer"] = 0.01
    assert decide(rules, s, "candidate")["verdict"] == "fail"


# --- REQ-404 -----------------------------------------------------------------------

def test_ablation_dashboard(tmp_path):
    runs = {
        "base": {"si_sdr": 10.0, "wer": 0.20},
        "-reverb": {"si_sdr": 8.0, "wer": 0.23},
        "-motion": {"si_sdr": 9.5, "wer": 0.21},
        "-adaptation": {"si_sdr": 9.0, "wer": 0.22},
        "-device": {"si_sdr": 9.8, "wer": 0.205},
        "-adaptation+-reverb": {"si_sdr": 6.5, "wer": 0.26},
    }
    att = attribution(runs)
    assert set(att["impact"]) == {"reverb", "motion", "adaptation", "device"}
    assert att["impact"]["reverb"]["si_sdr"]["impact_pct"] == pytest.approx(-20.0)
    assert att["impact"]["reverb"]["wer"]["impact_pct"] == pytest.approx(15.0)
    assert att["interactions"]["adaptation+reverb"]["si_sdr"] == pytest.approx(-0.5)
    assert att["factors_missing_metrics"] == []
    assert att["delta_correlation"]["si_sdr~wer"] < -0.9
    out = write_dashboard(att, str(tmp_path))
    assert os.path.getsize(out["pdf"]) > 1000 and "reverb" in open(out["markdown"], encoding="utf-8").read()


# --- W414 tracking -----------------------------------------------------------------------

def test_tracking_metrics_unit():
    times = [0, 0.1, 0.2, 0.3]
    truth = {"a": [(10, 0), (12, 0), (14, 0), None]}
    est = {"x": [(11, 0), (40, 0), (15, 0), (20, 0)]}
    m = tracking_metrics(truth, est, times, gate_deg=10)
    assert m["recall"] == pytest.approx(2 / 3) and m["precision"] == pytest.approx(2 / 4)
    assert m["fragmentations"] == 1.0 and m["mean_error_deg"] == pytest.approx(1.0)


def test_tracking_moving_source(tmp_path):
    from simulator.if_modules.orchestration import simulate_scene
    from simulator.uf.w151_config import SceneConfigValidator
    from training.systems import mic_positions
    c = [4.0, 1.2, 3.0]
    cfg = SceneConfigValidator().validate({
        "scene_id": "trk", "seed": 2,
        "room": {"type": "shoebox", "dimensions": {"L": 8.0, "W": 6.0, "H": 3.0}},
        "materials": {"default": "acoustic_tile"},
        "sources": [{"source_id": "s0", "motion": {"type": "linear", "start": [1.5, 1.2, 1.5], "end": [6.5, 1.2, 1.5]}}],
        "receivers": [{"receiver_id": f"m{i}", "position": [c[0] + dx, c[1], c[2] + dz]}
                      for i, (dx, dz) in enumerate(((0.05, 0), (0, 0.05), (-0.05, 0), (0, -0.05)))],
        "motion": {"duration_s": 3.0}, "ism_order": 1,
        "render": {"profile": "dynamic_v1", "fractional_delay": True},
        "output_dir": str(tmp_path),
    })
    b = load_scene(simulate_scene(cfg)["manifest_path"])
    times, est = track_azimuths(b.mixture, b.fs, mic_positions(b), b.reference_channel, 1)
    truth = truth_tracks(b.manifest["labels"]["doa_trace"], times, b.manifest["labels"]["vad"], b.fs)
    m = tracking_metrics(truth, est, times, gate_deg=20)
    assert m["recall"] > 0.8 and m["mean_error_deg"] < 8.0
