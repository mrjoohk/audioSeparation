"""
Stage 7 domain-gap experiment on a PROXY "real" domain (no real recordings here).

Source domain   : synthetic rooms, circular4 array, clean device chain.
Proxy-real      : other rooms with calibrated RT60 (profile fitted by blind
                  RT60 on proxy-dev), octave-band reverb, band-limited device,
                  channel sensitivity mismatch, three held-out arrays.
Models          : M0 baseline, M1 augmented + normalised features (REQ-303),
                  M2 = M1 + CORAL on unlabeled proxy-dev (REQ-304).
Adoption        : the model with a positive paired 95 % CI on proxy-dev SI-SDRi
                  vs M0 (design §6.3); BCE is reported as a diagnostic only.

    .venv/Scripts/python.exe scripts/run_domain_gap_experiment.py --workers 8
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
from datagen.publish import generate_dataset, publish_release, qc_gate  # noqa: E402
from datatools.loader import load_scene  # noqa: E402
from evaluation.ablation import attribution, write_dashboard  # noqa: E402
from evaluation.compare import evaluate_systems  # noqa: E402
from training.adaptation import domain_bce  # noqa: E402
from training.augment import AugmentConfig  # noqa: E402
from training.calibration import blind_rt60, fit_profile, kl_divergence  # noqa: E402
from training.experiment import release_identity, write_experiment  # noqa: E402
from training.models import MaskModelConfig, RidgeMaskModel  # noqa: E402
from training.systems import MaskCandidate, Unprocessed  # noqa: E402
from training.train import fit_coral, release_scenes, scene_features, train_from_release  # noqa: E402

UNSEEN_ARRAYS = ("circular3_r3", "linear3_4cm", "square4_8cm")


def build(lib, prior, rooms, pools, split, n, seed, out, mutate=None):
    plans = sample_scenarios(prior, n, lib, pools, rooms, split, seed=seed, output_dir=out)
    if mutate:
        for p in plans:
            mutate(p)
    return plans


def release(plans, out, name, workers):
    generate_dataset(plans, out, workers=workers)
    acc, rej = qc_gate(out, plans)
    return publish_release(out, acc, rej, name, "1.0.0", shard_size=64)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--n-train", type=int, default=100)
    ap.add_argument("--n-eval", type=int, default=24)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--name", default="domain_gap_v1")
    a = ap.parse_args()
    out_dir = ROOT / "reports" / "experiments" / a.name
    work = tempfile.mkdtemp(prefix="gap_")
    rng = np.random.default_rng(a.seed)
    try:
        lib = build_synthetic_library(os.path.join(work, "assets"), n_speakers=30, utts_per_speaker=3, seed=a.seed)
        src_prior = ScenarioPrior(arrays=("circular4",), duration_s=4.0, ism_order=2, n_speakers=(2, 2),
                                  tiers={"medium": 0.2}, tier_weights={"medium": 1}, noise_prob=0.5,
                                  event_prob=0.0, materials=("wood", "brick"), storage_profile="training")
        rooms = make_room_catalog(src_prior, seed=a.seed)
        pools = split_pools(lib, rooms, {"train": 0.6, "test": 0.1, "pdev": 0.15, "ptest": 0.15}, seed=a.seed)

        def proxy_device(p):
            c = p["config"]
            c["render"]["band_reverb"] = True
            c["impairments"] = {"type": "bandwidth", "bandwidth_hz": 4000.0}
            for r in c["receivers"]:
                r["sensitivity_db"] = round(float(rng.uniform(-2, 2)), 2)

        # source domain
        d_src = os.path.join(work, "src")
        plans = build(lib, src_prior, rooms, pools, "train", a.n_train, a.seed + 1, d_src)
        plans += build(lib, src_prior, rooms, pools, "test", a.n_eval, a.seed + 2, d_src)
        rel_src = release(plans, d_src, "gap-src", a.workers)

        # proxy-real dev (circular4, uncalibrated rooms) → calibration profile by blind RT60
        d_pdev = os.path.join(work, "pdev")
        pdev_prior = replace(src_prior, materials=("carpet", "acoustic_tile", "concrete"), noise_prob=0.3,
                             snr_db=(10.0, 25.0))
        plans_dev = build(lib, pdev_prior, rooms, pools, "pdev", a.n_eval, a.seed + 3, d_pdev, proxy_device)
        rel_pdev = release(plans_dev, d_pdev, "gap-pdev", a.workers)
        dev_scenes = release_scenes(rel_pdev, d_pdev, "pdev")
        est = {Path(m).parent.name: blind_rt60(load_scene(m).mixture[0], 16000) for m, _ in dev_scenes}
        profile = fit_profile(est, data_version=release_identity(rel_pdev)["release_manifest_sha256"][:12])

        # proxy-real test: calibrated by the profile, held-out arrays
        d_pt = os.path.join(work, "ptest")
        pt_prior = replace(pdev_prior, arrays=UNSEEN_ARRAYS, calibration=profile)
        plans_pt = build(lib, pt_prior, rooms, pools, "ptest", a.n_eval, a.seed + 4, d_pt, proxy_device)
        rel_pt = release(plans_pt, d_pt, "gap-ptest", a.workers)
        pt_scenes = release_scenes(rel_pt, d_pt, "ptest")
        est_pt = [blind_rt60(load_scene(m).mixture[0], 16000) for m, _ in pt_scenes]
        kl = kl_divergence([v for v in est.values() if v], [v for v in est_pt if v],
                           bins=np.linspace(0.0, 2.0, 11))

        # models
        cfg0 = MaskModelConfig()
        cfg1 = MaskModelConfig(normalize=True)
        e0 = train_from_release(rel_src, d_src, str(out_dir / "M0"), config=cfg0, seed=a.seed)
        e1 = train_from_release(rel_src, d_src, str(out_dir / "M1"), config=cfg1, seed=a.seed,
                                augment=AugmentConfig(), n_augment=2)
        m0 = RidgeMaskModel.load(str(out_dir / "M0" / "mask_model.npz"))
        m1 = RidgeMaskModel.load(str(out_dir / "M1" / "mask_model.npz"))
        src_train = release_scenes(rel_src, d_src, "train")
        coral = fit_coral(src_train[:40], dev_scenes, context=cfg1.context, normalize=True)
        coral0 = fit_coral(src_train[:40], dev_scenes, context=cfg0.context, normalize=False)

        # diagnostic BCE (frames of one bin band, source vs proxy)
        def frames(scenes, adapter=None):
            rows = []
            for m, fp in scenes[:8]:
                for f in scene_features(load_scene(m, expected_fingerprint=fp), cfg1.context, True):
                    f = adapter.transform(f) if adapter else f
                    rows.append(f[60, :, :-1])
            return np.vstack(rows)
        bce_before = domain_bce(frames(src_train), frames(dev_scenes))
        bce_after = domain_bce(frames(src_train), frames(dev_scenes, coral))

        systems = [Unprocessed(), MaskCandidate(m0, name="M0_baseline"), MaskCandidate(m1, name="M1_augmented"),
                   MaskCandidate(m1, adapter=coral, name="M2_aug_coral"),
                   MaskCandidate(m0, adapter=coral0, name="M3_coral_only")]
        refs = ["unprocessed", "M0_baseline"]
        r_in = evaluate_systems(release_scenes(rel_src, d_src, "test"), systems, "M1_augmented", refs,
                                out_dir=str(out_dir / "eval_in_domain"), title="in-domain (source test)")
        r_dev = evaluate_systems(dev_scenes, systems, "M2_aug_coral", refs + ["M1_augmented"],
                                 out_dir=str(out_dir / "eval_proxy_dev"), title="proxy-real dev")
        r_pt = evaluate_systems(pt_scenes, systems, "M1_augmented", refs,
                                out_dir=str(out_dir / "eval_proxy_test"), title="proxy-real test (held-out arrays)")

        # adoption on dev (design §6.3): positive CI lower bound vs M0
        def lower(rep, cand):
            k = f"{cand}-vs-M0_baseline:si_sdri_db"
            return rep["summary"]["paired"].get(k, {}).get("ci95", [float("nan")])[0]
        r_dev1 = evaluate_systems(dev_scenes, systems, "M1_augmented", refs, out_dir=None)
        cands = {"M1_augmented": lower(r_dev1, "M1_augmented"), "M2_aug_coral": lower(r_dev, "M2_aug_coral")}
        adopted = max((k for k, v in cands.items() if v > 0), key=lambda k: cands[k], default="M0_baseline")

        means = lambda rep: rep["summary"]["means"]
        in_m, pt_m = means(r_in), means(r_pt)
        # REQ-303: per held-out array degradation vs in-domain
        by_arr = {}
        plan_arr = {p["config"]["scene_id"]: p["plan"]["array"] for p in plans_pt}
        for row in r_pt["rows"]:
            by_arr.setdefault((plan_arr[row["scene_id"]], row["system"]), []).append(row["si_sdri_db"])
        deg = {}
        for arr in UNSEEN_ARRAYS:
            d0 = in_m["M0_baseline"]["si_sdri_db"] - np.mean(by_arr.get((arr, "M0_baseline"), [np.nan]))
            d1 = in_m["M1_augmented"]["si_sdri_db"] - np.mean(by_arr.get((arr, "M1_augmented"), [np.nan]))
            deg[arr] = {"M0_drop_db": float(d0), "M1_drop_db": float(d1),
                        "halved": bool(d1 <= 0.5 * d0) if d0 > 0 else None}
        gain_unseen = pt_m["M1_augmented"]["si_sdri_db"] - pt_m["M0_baseline"]["si_sdri_db"]
        summary = {
            "proxy_domain_note": "No real recordings: the 'real' domain is a simulated proxy (other rooms, band reverb, 4 kHz device, sensitivity mismatch, held-out arrays).",
            "calibration": {"profile_id": profile["id"], "rt60_median_s": profile["rt60_median_s"],
                            "kl_measured_vs_regenerated": kl, "req302_kl_le_0_1": kl <= 0.1},
            "req303": {"unseen_gain_M1_vs_M0_db": gain_unseen, "req303_gain_ge_1_5db": gain_unseen >= 1.5,
                       "per_array": deg},
            "req304": {"domain_bce_before": bce_before, "domain_bce_after": bce_after,
                       "note": "diagnostic only (design §6.3)"},
            "adoption": {"dev_ci_lower_vs_M0": cands, "adopted": adopted},
            "means": {"in_domain": in_m, "proxy_dev": means(r_dev), "proxy_test": pt_m},
        }
        write_experiment(str(out_dir / "experiment.json"), kind="domain_gap", config={"augment": AugmentConfig().__dict__},
                         seed=a.seed, data={"source": release_identity(rel_src), "proxy_dev": release_identity(rel_pdev),
                                            "proxy_test": release_identity(rel_pt), "calibration_profile": profile},
                         checkpoint={"M0": e0["checkpoint"], "M1": e1["checkpoint"]}, metrics=summary)
        # REQ-404: factor attribution on proxy-real test (base = full system M2)
        abl_runs = {
            "base": pt_m["M2_aug_coral"],
            "-adaptation": pt_m["M1_augmented"],
            "-augmentation": pt_m["M3_coral_only"],
            "-adaptation+-augmentation": pt_m["M0_baseline"],
        }
        att = attribution({k: {m: v[m] for m in ("si_sdri_db", "der") if m in v} for k, v in abl_runs.items()})
        dash = write_dashboard(att, str(ROOT / "reports" / "experiments" / "ablation_v1"),
                               title="Proxy-real test: removing augmentation / adaptation")
        summary["ablation"] = {"dashboard": str(Path(dash["pdf"]).relative_to(ROOT)), "impact": att["impact"],
                               "interactions": att["interactions"]}
        with open(out_dir / "summary.json", "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)
        sys.stdout.buffer.write(json.dumps(summary, indent=1).encode("utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
