"""
REQ-303 robustness experiment with the neural separator (synthetic stand-ins).

Protocol v2 (fixed before the run; v1 results in summary_v1.json):
Baseline : trained on ONE room template ("room A", wood/brick materials), circular4,
           no augmentation.
Robust   : trained on many wood/brick rooms and arrays (circular4, pair10,
           circular4_r10) with device/environment augmentation (training.augment).
Room B   : "completely unseen domain" (REQ-303 wording: device/environment
           mismatch) = the proxy-real domain of run_domain_gap_experiment.py:
           unseen rooms with unseen materials (carpet/acoustic_tile/concrete),
           octave-band reverb, 4 kHz device bandwidth, +-2 dB mic sensitivity
           mismatch, diffuse noise (p=0.3, 10-25 dB SNR); circular4.
Arrays   : three held-out arrays (circular3_r3, linear3_4cm, square4_8cm) in
           unseen wood/brick rooms.  The array-induced drop of each model is its
           score on the matched control (circular4, same unseen-room pool and
           generator) minus its score on the held-out array.  The room-A
           referenced drop (v1 definition) is reported as well.
Robust recipe "dr" (default, v3): the robust training set additionally uses
domain randomization -- RT60 drawn uniformly from a broad 0.15-1.2 s grid via
inverse-Sabine absorption, and octave-band reverb on half of the scenes.  The
range is generic, not fitted to room B.  "--robust-recipe plain" reproduces v2.
Acceptance (REQ-303): robust >= baseline + 1.5 dB on room B, and on every
held-out array the robust drop is at most half the baseline drop.

    .venv/Scripts/python.exe scripts/run_robustness_experiment.py --steps 3000 --workers 8
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from datagen.assets import build_synthetic_library  # noqa: E402
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools  # noqa: E402
from datagen.publish import generate_dataset  # noqa: E402
from evaluation.compare import evaluate_systems  # noqa: E402
from training.augment import AugmentConfig  # noqa: E402
from training.neural import NeuralSeparator, load_net, train_net  # noqa: E402

HELD_OUT = ("circular3_r3", "linear3_4cm", "square4_8cm")


def scenes(plans, out):
    return [(os.path.join(out, p["config"]["scene_id"], "scene_manifest.json"), None) for p in plans
            if os.path.exists(os.path.join(out, p["config"]["scene_id"], "scene_manifest.json"))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--n-train", type=int, default=1000)
    ap.add_argument("--n-test", type=int, default=60)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--robust-recipe", choices=("dr", "plain"), default="dr")
    a = ap.parse_args()
    out = ROOT / "reports" / "experiments" / "req303_neural"
    out.mkdir(parents=True, exist_ok=True)
    work = tempfile.mkdtemp(prefix="req303_")
    try:
        lib = build_synthetic_library(os.path.join(work, "assets"), n_speakers=80, utt_s=4.0, seed=a.seed)
        base = ScenarioPrior(arrays=("circular4",), duration_s=4.0, ism_order=2, n_speakers=(2, 2),
                             tiers={"medium": 0.2, "hard": 0.5}, tier_weights={"medium": 1, "hard": 1},
                             noise_prob=0.0, event_prob=0.0, storage_profile="training", n_room_templates=40,
                             materials=("wood", "brick"))
        rooms = make_room_catalog(base, seed=a.seed)
        pools = split_pools(lib, rooms, {"train": 0.8, "test": 0.2}, seed=a.seed)
        room_a = pools["train"]["rooms"][0]
        pools_a = {"train": {**pools["train"], "rooms": [room_a]}, "test": {**pools["test"], "rooms": [room_a]}}

        dev_rng = np.random.default_rng(a.seed + 99)

        def proxy_device(p):
            c = p["config"]
            c["render"]["band_reverb"] = True
            c["impairments"] = {"type": "bandwidth", "bandwidth_hz": 4000.0}
            for r in c["receivers"]:
                r["sensitivity_db"] = round(float(dev_rng.uniform(-2, 2)), 2)

        def gen(prior, pool, split, n, seed, name, mutate=None):
            d = os.path.join(work, name)
            plans = sample_scenarios(prior, n, lib, pool, rooms, split, seed=seed, output_dir=d)
            for p in plans:
                if mutate:
                    mutate(p)
            generate_dataset(plans, d, workers=a.workers)
            return scenes(plans, d), plans

        tr_a, _ = gen(base, pools_a, "train", a.n_train, a.seed + 1, "train_a")
        robust_prior = replace(base, arrays=("circular4", "pair10", "circular4_r10"))
        dr_rng = np.random.default_rng(a.seed + 77)

        def randomize(p):
            p["config"]["render"]["band_reverb"] = bool(dr_rng.random() < 0.5)

        if a.robust_recipe == "dr":
            robust_prior = replace(robust_prior, calibration={
                "id": "domain-randomization", "rt60_samples": [round(float(v), 3) for v in np.linspace(0.15, 1.2, 22)]})
        tr_r, _ = gen(robust_prior, pools, "train", a.n_train, a.seed + 2, "train_r",
                      randomize if a.robust_recipe == "dr" else None)
        te_a, _ = gen(base, pools_a, "test", a.n_test, a.seed + 3, "test_a")          # room A, unseen speakers
        proxy_prior = replace(base, materials=("carpet", "acoustic_tile", "concrete"), noise_prob=0.3,
                              snr_db=(10.0, 25.0))
        te_b, _ = gen(proxy_prior, pools, "test", a.n_test, a.seed + 4, "test_b", proxy_device)  # new domain
        te_c, _ = gen(base, pools, "test", a.n_test, a.seed + 8, "test_ctrl")           # unseen rooms, circular4
        te_arr = {arr: gen(replace(base, arrays=(arr,)), pools, "test", a.n_test, a.seed + 5 + i, f"test_{arr}")[0]
                  for i, arr in enumerate(HELD_OUT)}

        train_net(tr_a, str(out / "baseline_roomA"), steps=a.steps, seed=a.seed)
        train_net(tr_r, str(out / "robust"), steps=a.steps, seed=a.seed, augment=AugmentConfig())
        systems = [NeuralSeparator(load_net(str(out / "baseline_roomA" / "masknet.pt")), name="baseline_roomA"),
                   NeuralSeparator(load_net(str(out / "robust" / "masknet.pt")), name="robust")]

        def ev(sc, name):
            r = evaluate_systems(sc, systems, "robust", ["baseline_roomA"], out_dir=str(out / f"eval_{name}"), title=name)
            return {k: v["si_sdri_db"] for k, v in r["summary"]["means"].items()}, \
                r["summary"]["paired"].get("robust-vs-baseline_roomA:si_sdri_db")

        res = {"room_A": ev(te_a, "room_A"), "room_B": ev(te_b, "room_B"), "ctrl_circular4": ev(te_c, "ctrl")}
        for arr, sc in te_arr.items():
            res[arr] = ev(sc, arr)
        a_b, a_r = res["room_A"][0]["baseline_roomA"], res["room_A"][0]["robust"]
        c_b, c_r = res["ctrl_circular4"][0]["baseline_roomA"], res["ctrl_circular4"][0]["robust"]

        def halved(db, dr):
            return bool(dr <= 0.5 * db) if db > 0 else bool(dr <= 0)

        per_array = {}
        for arr in HELD_OUT:
            db, dr = c_b - res[arr][0]["baseline_roomA"], c_r - res[arr][0]["robust"]
            vb, vr = a_b - res[arr][0]["baseline_roomA"], a_r - res[arr][0]["robust"]
            per_array[arr] = {"baseline_drop_db": db, "robust_drop_db": dr, "halved": halved(db, dr),
                              "roomA_ref": {"baseline_drop_db": vb, "robust_drop_db": vr, "halved": halved(vb, vr)}}
        gain_b = res["room_B"][0]["robust"] - res["room_B"][0]["baseline_roomA"]
        summary = {
            "protocol": "v2", "robust_recipe": a.robust_recipe, "seed": a.seed, "n_test": a.n_test, "steps": a.steps,
            "means_si_sdri_db": {k: v[0] for k, v in res.items()},
            "paired_robust_vs_baseline": {k: v[1] for k, v in res.items()},
            "room_B_gain_db": gain_b, "req303_gain_ge_1_5db": gain_b >= 1.5,
            "held_out_arrays": per_array,
            "req303_all_arrays_halved": all(v["halved"] for v in per_array.values()),
            "note": "synthetic stand-in assets; not real speech",
        }
        with open(out / "summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)
        sys.stdout.buffer.write(json.dumps(summary, indent=1).encode("utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
