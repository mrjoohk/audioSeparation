"""
REQ-401 benchmark: 1 hour of synthetic 2-speaker overlapped speech (360 × 10 s,
unseen speakers and rooms), locked with the REQ-403 benchmark mechanism, and the
neural separator trained on a disjoint W2 release.

    .venv/Scripts/python.exe scripts/run_neural_benchmark.py --steps 4000 --workers 8

Writes reports/experiments/req401_neural/ (training/eval experiment manifests,
benchmark spec, comparison report, req401_summary.json).
Synthetic stand-in assets: results describe the pipeline on these signals, not
real speech.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datagen.assets import build_synthetic_library  # noqa: E402
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools  # noqa: E402
from datagen.publish import generate_dataset, publish_release, qc_gate  # noqa: E402
from evaluation.benchmark import load_benchmark, lock_benchmark  # noqa: E402
from evaluation.compare import evaluate_systems  # noqa: E402
from training.experiment import release_identity, write_experiment  # noqa: E402
from training.neural import NeuralSeparator, load_net, train_net  # noqa: E402
from training.systems import Unprocessed  # noqa: E402
from training.train import release_scenes  # noqa: E402

RT60S = [0.2, 0.3, 0.4, 0.5, 0.6]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--n-train", type=int, default=1500)
    ap.add_argument("--n-bench", type=int, default=360)
    ap.add_argument("--bench-seconds", type=float, default=10.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default="req401_neural")
    a = ap.parse_args()
    out = ROOT / "reports" / "experiments" / a.name
    out.mkdir(parents=True, exist_ok=True)
    work = tempfile.mkdtemp(prefix="req401_")
    try:
        lib = build_synthetic_library(os.path.join(work, "assets"), n_speakers=80, utts_per_speaker=3,
                                      n_noises=4, utt_s=6.0, seed=a.seed)
        base = dict(arrays=("circular4",), ism_order=2, n_speakers=(2, 2),
                    tiers={"medium": 0.2, "hard": 0.5}, tier_weights={"medium": 1, "hard": 1},
                    noise_prob=0.0, event_prob=0.0, storage_profile="training",
                    calibration={"id": "rt60-grid", "rt60_samples": RT60S})
        train_prior = ScenarioPrior(duration_s=4.0, **base)
        bench_prior = ScenarioPrior(duration_s=a.bench_seconds, **base)
        rooms = make_room_catalog(train_prior, seed=a.seed)
        pools = split_pools(lib, rooms, {"train": 0.8, "test": 0.2}, seed=a.seed)

        d_tr = os.path.join(work, "train")
        tr = sample_scenarios(train_prior, a.n_train, lib, pools, rooms, "train", seed=a.seed + 1, output_dir=d_tr)
        generate_dataset(tr, d_tr, workers=a.workers)
        acc, rej = qc_gate(d_tr, tr)
        rel_tr = publish_release(d_tr, acc, rej, "req401-train", "1.0.0", shard_size=256)

        d_be = os.path.join(work, "bench")
        be = sample_scenarios(bench_prior, a.n_bench, lib, pools, rooms, "test", seed=a.seed + 2, output_dir=d_be)
        generate_dataset(be, d_be, workers=a.workers)
        acc_b, rej_b = qc_gate(d_be, be)
        rel_be = publish_release(d_be, acc_b, rej_b, "req401-bench", "1.0.0", shard_size=128)
        spec = out / "benchmark_spec.yaml"
        lock_benchmark(rel_be, "test", "synthmeet-2spk-1h", "1.0", str(spec), os.path.join(work, "cache0"))

        exp = train_net(release_scenes(rel_tr, d_tr, "train"), str(out / "train"), steps=a.steps, seed=a.seed,
                        data_identity={**release_identity(rel_tr), "split": "train"})
        net = load_net(str(out / "train" / "masknet.pt"))

        t0 = time.time()
        bench = load_benchmark(str(spec), rel_be, os.path.join(work, "cache1"))
        rep = evaluate_systems(bench["scenes"], [Unprocessed(), NeuralSeparator(net)], "candidate_net",
                               ["unprocessed"], out_dir=str(out / "eval"),
                               title="REQ-401: 1 h synthetic 2-speaker benchmark")
        eval_s = time.time() - t0
        audio_s = sum(1 for _ in bench["scenes"]) * a.bench_seconds
        m = rep["summary"]["means"]["candidate_net"]
        summary = {
            "benchmark": {"spec": str(spec.relative_to(ROOT)), "n_scenes": len(bench["scenes"]),
                          "audio_hours": audio_s / 3600.0, "data_sha256": bench["data_sha256"]},
            "si_sdri_db_mean": m["si_sdri_db"], "der_mean": m.get("der"),
            "paired_vs_unprocessed": rep["summary"]["paired"].get("candidate_net-vs-unprocessed:si_sdri_db"),
            "evaluation_wall_s": eval_s, "evaluation_rtf": eval_s / audio_s,
            "req401_si_sdri_ge_8db": m["si_sdri_db"] >= 8.0,
            "req401_eval_within_1h": eval_s < 3600.0,
            "train_checkpoint": exp["checkpoint"], "train_time_s": exp["metrics"]["train_time_s"],
            "note": "synthetic speech-like stand-in assets; not real speech",
        }
        write_experiment(str(out / "eval" / "experiment.json"), kind="req401_benchmark",
                         config={"systems": ["unprocessed", "candidate_net"]}, seed=a.seed,
                         data={**release_identity(rel_be), "split": "test"}, checkpoint=exp["checkpoint"],
                         metrics=summary, evaluator={"module": "evaluation.compare", "pit": True})
        with open(out / "req401_summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)
        sys.stdout.buffer.write(json.dumps(summary, indent=1).encode("utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
