"""
Dataset generation, QC gate and versioned release (REQ-202, REQ-203, REQ-205, REQ-206; F-04, F-11).

Flow:
    plans ──generate_dataset──▶ rendered scenes (W1, checkpointed)
          ──qc_gate──────────▶ accepted / rejected (reason)
          ──publish_release──▶ releases/<name>-v<version>/
                                  shards/shard-XXXXX.tar, index.json, train/val/test.txt,
                                  qc_report.json, rejected.txt, release_manifest.json

A release directory is immutable: publishing the same version twice fails.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tarfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from datatools.loader import SceneContractError, load_scene
from datatools.splits import check_split_leakage

CLIP_LEVEL = 0.99          # REQ-205: max |amplitude| >= 0.99 is clipping
SILENCE_DBFS = -60.0       # mixture RMS below this is silence
SNR_TOLERANCE_DB = 1.0     # REQ-202
LEAKAGE_KEYS = ("speaker", "noise", "room", "event")


class ReleaseError(RuntimeError):
    pass


def generate_dataset(plans: Sequence[dict], output_dir: str, workers: int = 1,
                     verify: str = "checksum"):
    """Render plans with the W1 batch runner (checkpointed, verified resume)."""
    from simulator.if_modules.orchestration import simulate_scene
    from simulator.uf.w151_config import SceneConfigValidator
    from simulator.uf.w152_batch import run_batch
    cfgs = []
    for p in plans:
        c = dict(p["config"], output_dir=output_dir)
        cfgs.append(SceneConfigValidator().validate(c))
    return run_batch(cfgs, worker_count=workers, output_dir=output_dir, simulate_fn=simulate_scene,
                     checkpoint_file=os.path.join(output_dir, "batch_checkpoint.json"), verify=verify)


def _rms_dbfs(x: np.ndarray) -> float:
    r = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
    return 20.0 * math.log10(r * math.sqrt(2.0)) if r > 0 else -math.inf   # AES17


def qc_gate(output_dir: str, plans: Sequence[dict]) -> Tuple[List[dict], List[dict]]:
    """Apply dataset QC rules to rendered scenes.

    Returns:
        (accepted entries, rejected [{scene_id, reason}])
    """
    accepted, rejected = [], []
    for p in plans:
        sid = p["config"]["scene_id"]
        mpath = os.path.join(output_dir, sid, "scene_manifest.json")
        if not os.path.exists(mpath):
            rejected.append({"scene_id": sid, "reason": "not_rendered"})
            continue
        try:
            b = load_scene(mpath)
        except SceneContractError as exc:
            rejected.append({"scene_id": sid, "reason": f"contract:{exc}"[:120]})
            continue
        m = b.manifest
        reason = None
        peak = float(np.max(np.abs(b.mixture)))
        roles = m["labels"].get("roles", {})
        if peak >= CLIP_LEVEL:
            reason = "clipping"
        elif _rms_dbfs(b.mixture) < SILENCE_DBFS:
            reason = "silence"
        else:
            for si, s in enumerate(b.source_ids):
                if roles.get(s, "speech") == "speech" and not np.any(b.references[si]):
                    reason = "silent_reference"
                    break
        mix = m["labels"].get("mix") or {}
        if reason is None and "target_snr_db" in mix:
            if abs(mix["measured_snr_db"] - mix["target_snr_db"]) > SNR_TOLERANCE_DB:
                reason = "snr_out_of_tolerance"
        if reason:
            rejected.append({"scene_id": sid, "reason": reason})
            continue
        accepted.append({
            "scene_id": sid, "split": p["plan"]["split"], "tier": p["plan"]["tier"],
            "fingerprint": m["fingerprint"], "room_id": p["plan"]["room_id"],
            "speakers": p["plan"]["speakers"], "noise_id": p["plan"]["noise_id"],
            "event_ids": p["plan"].get("event_ids", []),
            "utterances": p["plan"]["utterances"],
            "target_overlap": p["plan"]["target_overlap"],
            "overlap_ratio_vad": m["labels"]["overlap_ratio_vad"],
            "vad_any_samples": _vad_count(m, roles, 1), "vad_multi_samples": _vad_count(m, roles, 2),
            "target_snr_db": mix.get("target_snr_db"), "measured_snr_db": mix.get("measured_snr_db"),
            "peak": peak, "n_samples": m["render"]["n_samples"], "fs": m["render"]["fs"],
        })
    return accepted, rejected


def _vad_count(m: dict, roles: Mapping[str, str], k: int) -> int:
    T = m["render"]["n_samples"]
    cnt = np.zeros(T, dtype=np.int16)
    for s, segs in m["labels"]["vad"].items():
        if roles.get(s, "speech") != "speech":
            continue
        for a, b in segs:
            cnt[a:b] += 1
    return int(np.sum(cnt >= k))


def leakage_audit(entries: Sequence[dict]) -> List[dict]:
    items = [{"id": e["scene_id"], "split": e["split"],
              "keys": {"speaker": e["speakers"], "noise": e["noise_id"], "room": e["room_id"],
                       "event": e.get("event_ids", [])}}
             for e in entries]
    return check_split_leakage(items, LEAKAGE_KEYS)


def tier_overlap_report(entries: Sequence[dict]) -> Dict[str, dict]:
    """Aggregate VAD overlap per tier (REQ-203: cumulative ratio within ±5 % of target)."""
    agg: Dict[str, dict] = defaultdict(lambda: {"any": 0, "multi": 0, "n": 0, "target": None})
    for e in entries:
        a = agg[e["tier"]]
        a["any"] += e["vad_any_samples"]
        a["multi"] += e["vad_multi_samples"]
        a["n"] += 1
        a["target"] = e["target_overlap"]
    out = {}
    for t, a in agg.items():
        ratio = a["multi"] / a["any"] if a["any"] else 0.0
        out[t] = {"n_scenes": a["n"], "target": a["target"], "cumulative_overlap": ratio,
                  "within_5pct": abs(ratio - a["target"]) < 0.05}
    return out


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def publish_release(output_dir: str, accepted: Sequence[dict], rejected: Sequence[dict],
                    name: str, version: str, release_root: Optional[str] = None,
                    shard_size: int = 64, extra: Optional[dict] = None) -> str:
    """Package accepted scenes into an immutable, versioned, sharded release."""
    rel = os.path.join(release_root or os.path.join(output_dir, "releases"), f"{name}-v{version}")
    if os.path.exists(rel):
        raise ReleaseError(f"release {rel} already exists (releases are immutable)")
    leaks = leakage_audit(accepted)
    if leaks:
        raise ReleaseError(f"split leakage: {leaks[0]}")
    clipped = [e["scene_id"] for e in accepted if e["peak"] >= CLIP_LEVEL]
    if clipped:
        raise ReleaseError(f"clipped scenes in release: {clipped[:3]}")
    os.makedirs(os.path.join(rel, "shards"))
    entries = sorted(accepted, key=lambda e: (e["split"], e["scene_id"]))
    index = []
    for k in range(0, len(entries), shard_size):
        shard = f"shards/shard-{k // shard_size:05d}.tar"
        with tarfile.open(os.path.join(rel, shard), "w") as tf:
            for e in entries[k:k + shard_size]:
                tf.add(os.path.join(output_dir, e["scene_id"]), arcname=e["scene_id"])
                index.append({**e, "shard": shard})
    splits = defaultdict(list)
    for e in index:
        splits[e["split"]].append(e["scene_id"])
    for sp, ids in splits.items():
        with open(os.path.join(rel, f"{sp}.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(ids) + "\n")
    reasons = Counter(r["reason"].split(":")[0] for r in rejected)
    snr_err = [abs(e["measured_snr_db"] - e["target_snr_db"]) for e in index if e["target_snr_db"] is not None]
    report = {
        "n_accepted": len(index), "n_rejected": len(rejected),
        "rejected_by_reason": dict(reasons),
        "per_split": {sp: len(ids) for sp, ids in splits.items()},
        "per_tier": dict(Counter(e["tier"] for e in index)),
        "tier_overlap": tier_overlap_report(index),
        "snr_abs_error_db_max": max(snr_err) if snr_err else None,
        "leakage": leaks,
        "clipped_in_release": 0,
    }
    meta = {
        "name": name, "version": version, "created_at": datetime.now(timezone.utc).isoformat(),
        "n_scenes": len(index), "splits": {sp: len(v) for sp, v in splits.items()},
        **(extra or {}),
    }
    with open(os.path.join(rel, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "scenes": index}, fh, indent=1)
    with open(os.path.join(rel, "qc_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    with open(os.path.join(rel, "rejected.txt"), "w", encoding="utf-8") as fh:
        fh.writelines(f"{r['scene_id']}\t{r['reason']}\n" for r in rejected)
    files = sorted(
        os.path.relpath(os.path.join(d, f), rel).replace(os.sep, "/")
        for d, _, fs in os.walk(rel) for f in fs
    )
    with open(os.path.join(rel, "release_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"name": name, "version": version,
                   "files": {f: _sha(os.path.join(rel, f)) for f in files}}, fh, indent=1)
    return rel


def verify_release(rel: str) -> Tuple[bool, List[str]]:
    with open(os.path.join(rel, "release_manifest.json"), encoding="utf-8") as fh:
        man = json.load(fh)
    bad = [f for f, h in man["files"].items()
           if not os.path.exists(os.path.join(rel, f)) or _sha(os.path.join(rel, f)) != h]
    return not bad, bad


def deficient_bins(entries: Sequence[dict], bin_fn: Callable[[dict], str],
                   wanted: Iterable[str], min_count: int) -> Dict[str, int]:
    """Bins with fewer than ``min_count`` accepted scenes → number missing."""
    c = Counter(bin_fn(e) for e in entries)
    return {b: min_count - c.get(b, 0) for b in wanted if c.get(b, 0) < min_count}


def supplement_plans(prior, deficits: Mapping[str, int], lib, pools, rooms, split: str,
                     seed: int, output_dir: str, id_prefix: str = "sup") -> List[dict]:
    """Extra plans for deficient tiers (bins are tier names)."""
    from datagen.planner import sample_scenarios
    out = []
    for j, (tier, k) in enumerate(sorted(deficits.items())):
        ps = sample_scenarios(prior, int(k), lib, pools, rooms, split, seed=seed + 1000 * j,
                              output_dir=output_dir, tier=tier)
        for i, p in enumerate(ps):
            p["config"]["scene_id"] = f"{split}_{id_prefix}{j}_{i:05d}"
        out.extend(ps)
    return out
