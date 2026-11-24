"""
First end-to-end experiment on synthetic data (stage 5):
W2 release → train candidate mask model → compare unprocessed / baseline_ds /
candidate_mask on the held-out test split → reports/experiments/<name>/.

    .venv/Scripts/python.exe scripts/run_baseline_experiment.py --train 120 --test 30 --workers 8

Uses synthetic stand-in assets (not speech): numbers show that the pipeline
works and how systems rank on these signals, not real-meeting performance.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datagen.assets import build_synthetic_library  # noqa: E402
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools  # noqa: E402
from datagen.publish import generate_dataset, publish_release, qc_gate  # noqa: E402
from evaluation.compare import evaluate_systems  # noqa: E402
from training.experiment import release_identity, write_experiment  # noqa: E402
from training.models import RidgeMaskModel  # noqa: E402
from training.systems import DelaySumBaseline, MaskCandidate, Unprocessed  # noqa: E402
from training.train import release_scenes, train_from_release  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=120)
    ap.add_argument("--test", type=int, default=30)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default="e2e_synthetic_v1")
    ap.add_argument("--keep", action="store_true", help="keep the rendered data")
    a = ap.parse_args()

    work = tempfile.mkdtemp(prefix="e2e_")
    out = ROOT / "reports" / "experiments" / a.name
    try:
        lib = build_synthetic_library(os.path.join(work, "assets"), n_speakers=24, utts_per_speaker=3,
                                      n_noises=8, seed=a.seed)
        prior = ScenarioPrior(arrays=("circular4", "pair10"), duration_s=4.0, ism_order=2,
                              n_speakers=(2, 2), tiers={"medium": 0.2, "hard": 0.5},
                              tier_weights={"medium": 1, "hard": 1}, storage_profile="training")
        rooms = make_room_catalog(prior, seed=a.seed)
        pools = split_pools(lib, rooms, {"train": 0.8, "test": 0.2}, seed=a.seed)
        render = os.path.join(work, "render")
        plans = sample_scenarios(prior, a.train, lib, pools, rooms, "train", seed=a.seed + 1, output_dir=render)
        plans += sample_scenarios(prior, a.test, lib, pools, rooms, "test", seed=a.seed + 2, output_dir=render)
        generate_dataset(plans, render, workers=a.workers)
        acc, rej = qc_gate(render, plans)
        rel = publish_release(render, acc, rej, "e2e-synth", "1.0.0", shard_size=64)
        exp = train_from_release(rel, render, str(out / "train"), split="train", seed=a.seed)
        model = RidgeMaskModel.load(str(out / "train" / "mask_model.npz"))
        systems = [Unprocessed(), DelaySumBaseline(), MaskCandidate(model)]
        report = evaluate_systems(release_scenes(rel, render, "test"), systems, candidate="candidate_mask",
                                  references=["unprocessed", "baseline_ds"], out_dir=str(out / "eval"),
                                  title=f"{a.name}: synthetic held-out test",
                                  meta={"release": release_identity(rel), "train_experiment": exp["checkpoint"]})
        write_experiment(str(out / "eval" / "experiment.json"), kind="evaluate", config={"systems": [s.name for s in systems]},
                         seed=a.seed, data={**release_identity(rel), "split": "test"},
                         checkpoint=exp["checkpoint"], metrics=report["summary"],
                         evaluator={"module": "evaluation.compare", "der_collar_s": 0.0, "si_sdri": "permutation, missing=0"})
        shutil.copy(os.path.join(rel, "qc_report.json"), out / "qc_report.json")
        print(json.dumps(report["summary"], indent=1))
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
