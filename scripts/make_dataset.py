"""
Build a versioned synthetic dataset release (W200000).

    .venv/Scripts/python.exe scripts/make_dataset.py --assets data/assets --out data/render \
        --name synthmeet --version 0.1.0 --train 800 --val 100 --test 100 --workers 8

If --assets has no assets.json, a synthetic stand-in library is created (not speech;
see datagen/assets.py).  Register real corpora with AssetLibrary.register_wav instead.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from datagen.assets import AssetLibrary, build_synthetic_library  # noqa: E402
from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools  # noqa: E402
from datagen.publish import generate_dataset, publish_release, qc_gate  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prior", default=str(ROOT / "configs" / "scenario_prior.yaml"))
    ap.add_argument("--assets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="synthmeet")
    ap.add_argument("--version", required=True)
    ap.add_argument("--train", type=int, default=80)
    ap.add_argument("--val", type=int, default=10)
    ap.add_argument("--test", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    prior = ScenarioPrior.from_dict(yaml.safe_load(open(a.prior, encoding="utf-8")))
    lib = AssetLibrary(a.assets)
    if not lib.assets:
        lib = build_synthetic_library(a.assets, seed=a.seed)
    rooms = make_room_catalog(prior, seed=a.seed)
    ratios = {"train": a.train, "val": a.val, "test": a.test}
    pools = split_pools(lib, rooms, ratios, seed=a.seed)
    plans = []
    for k, (split, n) in enumerate(ratios.items()):
        if n:
            plans += sample_scenarios(prior, n, lib, pools, rooms, split, seed=a.seed + 101 * k, output_dir=a.out)
    summary = generate_dataset(plans, a.out, workers=a.workers)
    acc, rej = qc_gate(a.out, plans)
    rel = publish_release(a.out, acc, rej, a.name, a.version, extra={
        "prior": yaml.safe_load(open(a.prior, encoding="utf-8")),
        "asset_library": str(Path(a.assets).resolve()),
        "synthetic_assets": all(x.synthetic for x in lib.assets.values()),
        "render_failures": summary.failure_reasons,
    })
    print(json.dumps({"release": rel, "accepted": len(acc), "rejected": len(rej)}, indent=1))


if __name__ == "__main__":
    main()
