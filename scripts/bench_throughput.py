"""
Throughput benchmark and F-11 pilot (REQ-W04, REQ-W10; audit F-11).

Usage:
    .venv/Scripts/python.exe scripts/bench_throughput.py --workers 8 --rirs 2000 --scenes 16

Writes to reports/perf/:
    rir_throughput_bench.csv       REQ-W04 evidence (RIR/s at 16 kHz, ISM order 3)
    scene_throughput_pilot.json    REQ-W10 + F-11 pilot (scenes/h, QC audio h/h, bytes/scene)
    pilot_report.md                human-readable summary
"""
from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import platform
import shutil
import sys
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _rir_worker(args):
    seed, n = args
    warnings.simplefilter("ignore")
    import numpy as np
    from simulator.uf.w151_config import SceneConfigValidator
    from simulator.if_modules.scene_world import SceneWorldBuilder
    from simulator.if_modules.propagation import AcousticPropagationEngine
    from simulator.uf.w115_scene_state import assemble_scene_state
    from simulator.types import SourceTrajectory, ReceiverTrajectory, TickState

    rng = np.random.default_rng(seed)
    cfg = SceneConfigValidator().validate({
        "scene_id": "bench", "seed": seed,
        "room": {"type": "shoebox", "dimensions": {"L": 6.0, "W": 5.0, "H": 3.0}},
        "materials": {"default": "wood"},
        "sources": [{"source_id": "s0", "position": [1, 1.5, 1]}],
        "receivers": [{"receiver_id": "r0", "position": [4, 1.2, 3]}],
    })
    b = SceneWorldBuilder(cfg, seed=seed)
    room, mats, obs = b.build_room(), b.build_materials(), b.build_obstacles()
    eng = AcousticPropagationEngine(fs=16000, ism_order=3, seed=seed)
    t0 = time.perf_counter()
    for i in range(n):
        sp = rng.uniform([0.5, 0.5, 0.5], [5.5, 2.5, 4.5])
        rp = rng.uniform([0.5, 0.5, 0.5], [5.5, 2.5, 4.5])
        st = [SourceTrajectory("s0", [TickState(0, 0.0, sp, np.zeros(3), 0.0)], 50.0)]
        rt = [ReceiverTrajectory("r0", [TickState(0, 0.0, rp, np.zeros(3), 0.0, np.array([0, 0, 0, 1.0]))], 50.0)]
        state = assemble_scene_state(room, mats, obs, st, rt, tick_id=i)
        eng.generate_rir(state, "s0", "r0")
        eng._rir_cache.clear()
    return n, time.perf_counter() - t0


def bench_rirs(total: int, workers: int) -> dict:
    per = max(1, total // workers)
    t0 = time.perf_counter()
    if workers == 1:
        res = [_rir_worker((0, per))]
    else:
        with mp.Pool(workers) as pool:
            res = pool.map(_rir_worker, [(i, per) for i in range(workers)])
    wall = time.perf_counter() - t0
    n = sum(r[0] for r in res)
    compute = max(r[1] for r in res)
    return {"workers": workers, "n_rirs": n, "wall_s": wall,
            "rirs_per_s": n / compute,                 # steady state (workers ready)
            "rirs_per_s_incl_startup": n / wall,       # includes Windows spawn + imports
            "single_worker_rirs_per_s": float(sum(r[0] / r[1] for r in res) / len(res))}


def scene_configs(n: int, duration_s: float, out: str, storage: str):
    from simulator.uf.w151_config import SceneConfigValidator
    import numpy as np
    rng = np.random.default_rng(123)
    cfgs = []
    for i in range(n):
        L, W, H = rng.uniform(4, 9), rng.uniform(3.5, 7), rng.uniform(2.6, 3.5)
        pt = lambda: [float(rng.uniform(0.5, L - 0.5)), float(rng.uniform(1.0, H - 0.5)), float(rng.uniform(0.5, W - 0.5))]
        cx, cz = L / 2, W / 2
        mics = [[cx + dx, 1.2, cz + dz] for dx, dz in ((0.05, 0.05), (-0.05, 0.05), (-0.05, -0.05), (0.05, -0.05))]
        cfgs.append(SceneConfigValidator().validate({
            "scene_id": f"pilot_{i:04d}", "seed": int(rng.integers(1 << 30)),
            "room": {"type": "shoebox", "dimensions": {"L": L, "W": W, "H": H}},
            "materials": {"default": str(rng.choice(["wood", "carpet", "brick", "acoustic_tile"]))},
            "sources": [{"source_id": f"spk{k}", "position": pt()} for k in range(2)],
            "receivers": [{"receiver_id": f"m{k}", "position": p} for k, p in enumerate(mics)],
            "motion": {"duration_s": duration_s},
            "ism_order": 3,
            "render": {"storage_profile": storage},
            "output_dir": out,
        }))
    return cfgs


def bench_scenes(n: int, workers: int, duration_s: float, storage: str) -> dict:
    from simulator.uf.w152_batch import run_batch
    from simulator.if_modules.orchestration import simulate_scene
    out = tempfile.mkdtemp(prefix="pilot_")
    try:
        cfgs = scene_configs(n, duration_s, out, storage)
        t0 = time.perf_counter()
        s = run_batch(cfgs, worker_count=workers, output_dir=out, simulate_fn=simulate_scene,
                      checkpoint_file=os.path.join(out, "ckpt.json"))
        wall = time.perf_counter() - t0
        n_ok = s.n_completed - s.n_skipped
        return {
            "storage_profile": storage, "workers": workers, "scenes": n,
            "scene_duration_s": duration_s, "sources": 2, "receivers": 4, "ism_order": 3,
            "completed": n_ok, "failed": s.n_failed, "failure_reasons": s.failure_reasons,
            "wall_s": wall, "scenes_per_hour": n_ok / wall * 3600.0,
            "audio_hours_rendered": s.audio_seconds_completed / 3600.0,
            "qc_passed_audio_hours_per_hour": s.qc_passed_audio_hours_per_hour,
            "bytes_written": s.bytes_written,
            "bytes_per_scene": s.bytes_written / max(n_ok, 1),
            "fail_rate": s.n_failed / n,
        }
    finally:
        shutil.rmtree(out, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rirs", type=int, default=2000)
    ap.add_argument("--scenes", type=int, default=16)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--out", default=str(ROOT / "reports" / "perf"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    env = {"python": platform.python_version(), "machine": platform.processor() or platform.machine(),
           "cpu_count": os.cpu_count(), "date": time.strftime("%Y-%m-%d")}

    rir1 = bench_rirs(min(a.rirs, 400), 1)
    rirn = bench_rirs(a.rirs, a.workers)
    with open(os.path.join(a.out, "rir_throughput_bench.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rirn))
        w.writeheader()
        w.writerow(rir1)
        w.writerow(rirn)

    full = bench_scenes(a.scenes, a.workers, a.duration, "full")
    train = bench_scenes(a.scenes, a.workers, a.duration, "training")
    pilot = {"env": env, "rir": [rir1, rirn], "scenes": [full, train],
             "targets": {"REQ-W04_rirs_per_s": 1000, "REQ-W10_scenes_per_hour_8core": 1000}}
    with open(os.path.join(a.out, "scene_throughput_pilot.json"), "w", encoding="utf-8") as fh:
        json.dump(pilot, fh, indent=2)

    def ok(v, t):
        return "met" if v >= t else "NOT met"
    gb100k_full = full["bytes_per_scene"] / full["scene_duration_s"] * 3600 * 1e5 / 1e12
    gb100k_train = train["bytes_per_scene"] / train["scene_duration_s"] * 3600 * 1e5 / 1e12
    md = f"""# Throughput benchmark and F-11 pilot ({env['date']})

Environment: Python {env['python']}, {env['cpu_count']} logical CPUs, workers = {a.workers}.

| Requirement | Target | Measured | Result |
| --- | --- | --- | --- |
| REQ-W04 RIR/s (16 kHz, ISM 3), single process | — | {rir1['rirs_per_s']:.0f} | — |
| REQ-W04 RIR/s, {a.workers} workers, steady state | 1000 | {rirn['rirs_per_s']:.0f} | {ok(rirn['rirs_per_s'], 1000)} |
| same, including process start-up ({rirn['wall_s']:.1f} s wall) | — | {rirn['rirs_per_s_incl_startup']:.0f} | — |
| REQ-W10 scenes/h (10 s, 2 src, 4 mic), {a.workers} workers, full storage | 1000 | {full['scenes_per_hour']:.0f} | {ok(full['scenes_per_hour'], 1000)} |
| same, training storage | 1000 | {train['scenes_per_hour']:.0f} | {ok(train['scenes_per_hour'], 1000)} |

## F-11 pilot ({a.scenes} scenes per profile)

| Profile | QC-passed audio h / h | MB per scene | Fail rate | Storage for 100k audio hours |
| --- | --- | --- | --- | --- |
| full | {full['qc_passed_audio_hours_per_hour']:.2f} | {full['bytes_per_scene']/1e6:.1f} | {full['fail_rate']:.0%} | {gb100k_full:.1f} TB |
| training | {train['qc_passed_audio_hours_per_hour']:.2f} | {train['bytes_per_scene']/1e6:.1f} | {train['fail_rate']:.0%} | {gb100k_train:.1f} TB |

"Audio hours" count rendered scene length (dry duration + reverb tail) per scene.
Storage extrapolation uses the measured bytes per audio second (float32, 4 channels, 2 sources).
"""
    with open(os.path.join(a.out, "pilot_report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    sys.stdout.buffer.write(md.encode("utf-8"))


if __name__ == "__main__":
    main()
