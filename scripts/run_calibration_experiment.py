"""
REQ-302 calibration experiment on a PROXY "real" domain.

1. Acceptance case: 100 recordings of rooms with RT60 ≈ 0.5 s → blind RT60
   median must lie in 0.5 ± 0.075 s.
2. Closed loop: proxy-real sessions (unknown rooms, octave-band reverb, 4 kHz
   device) → blind RT60 → profile → W2 renders → blind RT60 of the renders →
   quantile correction, until KL(measured, regenerated) <= 0.1.

Sample size: with 10 bins on 0-2 s, two n=60 samples of the SAME distribution
already give median KL ~0.12, so the 0.1 target is only measurable with
n >= ~200 (n=300: noise floor ~0.03).  Regenerated sets render every target
once ("stratified" assignment) instead of drawing with replacement.

    .venv/Scripts/python.exe scripts/run_calibration_experiment.py --workers 8
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datagen.assets import build_synthetic_library  # noqa: E402
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools  # noqa: E402
from datagen.publish import generate_dataset  # noqa: E402
from datatools.loader import load_scene  # noqa: E402
from training.calibration import blind_rt60, closed_loop_calibrate, fit_profile  # noqa: E402


def device(p):
    c = p["config"]
    c["render"]["band_reverb"] = True
    c["impairments"] = {"type": "bandwidth", "bandwidth_hz": 4000.0}


def render_and_measure(lib, prior, rooms, pools, n, seed, out, workers, mutate=device):
    plans = sample_scenarios(prior, n, lib, pools, rooms, "all", seed=seed, output_dir=out)
    for p in plans:
        mutate(p)
    generate_dataset(plans, out, workers=workers)
    vals = []
    for p in plans:
        mp = os.path.join(out, p["config"]["scene_id"], "scene_manifest.json")
        if os.path.exists(mp):
            vals.append(blind_rt60(load_scene(mp).mixture[0], 16000))
    return vals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    out_dir = ROOT / "reports" / "experiments" / "calibration_v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    work = tempfile.mkdtemp(prefix="calib_")
    counter = itertools.count()
    try:
        lib = build_synthetic_library(os.path.join(work, "assets"), n_speakers=20, utt_s=6.0, seed=a.seed)
        base = dict(arrays=("single",), duration_s=6.0, ism_order=3, n_speakers=(1, 1),
                    tiers={"easy": 0.0}, tier_weights={"easy": 1}, noise_prob=0.0, event_prob=0.0,
                    storage_profile="training")
        prior0 = ScenarioPrior(**base)
        rooms = make_room_catalog(prior0, seed=a.seed)
        pools = split_pools(lib, rooms, {"all": 1.0}, seed=a.seed)

        # 1) acceptance case: 100 rooms with RT60 0.5 s (no device impairment)
        acc = render_and_measure(lib, ScenarioPrior(**base, calibration={"id": "rt05", "rt60_samples": [0.5]}),
                                 rooms, pools, 100, a.seed + 1, os.path.join(work, "acc"), a.workers,
                                 mutate=lambda p: None)
        acc = [v for v in acc if v]
        median = float(np.median(acc))

        # 2) proxy-real sessions: unknown absorptive/reflective materials, band reverb, 4 kHz device
        real_prior = ScenarioPrior(**{**base, "materials": ("carpet", "wood", "brick", "acoustic_tile")})
        measured = render_and_measure(lib, real_prior, rooms, pools, a.n, a.seed + 2,
                                      os.path.join(work, "real"), a.workers)
        profile = fit_profile({f"s{i}": v for i, v in enumerate(measured)}, data_version="proxy-real-v1")

        def regenerate(targets):
            k = next(counter)
            pr = ScenarioPrior(**base, calibration={"id": f"iter{k}", "rt60_samples": targets,
                                                    "assignment": "stratified"})
            return render_and_measure(lib, pr, rooms, pools, len(targets), a.seed + 100 + k,
                                      os.path.join(work, f"regen{k}"), a.workers)

        loop = closed_loop_calibrate(profile["rt60_samples"], regenerate, iterations=3,
                                     bins=np.linspace(0.0, 2.0, 11))
        summary = {
            "proxy_domain_note": "proxy-real sessions are simulated (unknown materials, band reverb, 4 kHz device)",
            "acceptance_rt60_0_5": {"n": len(acc), "median_s": median, "within_0_075": abs(median - 0.5) <= 0.075},
            "profile": {k: profile[k] for k in ("id", "rt60_median_s", "parameter_ranges")},
            "closed_loop": loop["history"], "final_kl": loop["kl"], "req302_kl_le_0_1": loop["converged"],
            "calibrated_targets_median_s": float(np.median(loop["targets"])),
            "n_measured": len(measured), "kl_bins": "10 bins on 0-2 s",
        }
        with open(out_dir / "summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)
        sys.stdout.buffer.write(json.dumps(summary, indent=1).encode("utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
