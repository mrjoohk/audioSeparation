"""
Version-locked benchmarks (REQ-403; audit F-04).

A benchmark spec (YAML) pins a W2 release by name, version and the sha256 of
its ``release_manifest.json``, lists the split and the scene order, and records
the expected sha256 of the loaded data tensors.  Loading:

1. verifies the release manifest hash against the **declared** value (agreement
   between servers alone cannot catch that all of them read a wrong version);
2. verifies every release file (shards, index) against the release manifest;
3. materialises shards into a cache directory (self-contained: no dependency on
   the original render directory);
4. loads scenes in the pinned order and checks the data hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import tarfile
from typing import Dict, List, Optional, Tuple

import numpy as np

from datagen.publish import verify_release
from datatools.loader import load_scene
from datatools.splits import BenchmarkIntegrityError, verify_benchmark_manifest


def materialize_release(release_dir: str, cache_dir: str) -> str:
    """Verify a release and extract its shards into ``cache_dir`` (idempotent)."""
    ok, bad = verify_release(release_dir)
    if not ok:
        raise BenchmarkIntegrityError(f"release files changed or missing: {bad[:3]}")
    with open(os.path.join(release_dir, "index.json"), encoding="utf-8") as fh:
        idx = json.load(fh)
    shards = sorted({e["shard"] for e in idx["scenes"]})
    os.makedirs(cache_dir, exist_ok=True)
    for sh in shards:
        with tarfile.open(os.path.join(release_dir, sh)) as tf:
            members = [m for m in tf.getmembers() if not os.path.exists(os.path.join(cache_dir, m.name))]
            for m in members:
                if m.name.startswith(("/", "..")) or ".." in m.name.split("/"):
                    raise BenchmarkIntegrityError(f"unsafe path in shard: {m.name}")
            tf.extractall(cache_dir, members=members, filter="data")
    missing = [e["scene_id"] for e in idx["scenes"]
               if not os.path.exists(os.path.join(cache_dir, e["scene_id"], "scene_manifest.json"))]
    if missing:
        raise BenchmarkIntegrityError(f"scenes missing after extraction: {missing[:3]}")
    return cache_dir


def _tensor_hash(scenes: List[Tuple[str, str]], cache_dir: str) -> str:
    h = hashlib.sha256()
    for sid, fp in scenes:
        b = load_scene(os.path.join(cache_dir, sid, "scene_manifest.json"), expected_fingerprint=fp)
        h.update(sid.encode())
        h.update(np.ascontiguousarray(b.mixture).tobytes())
        h.update(np.ascontiguousarray(b.references).tobytes())
    return h.hexdigest()


def lock_benchmark(release_dir: str, split: str, name: str, version: str, out_path: str,
                   cache_dir: str) -> dict:
    """Create a benchmark spec pinned to a release split (deterministic order by scene_id)."""
    import yaml
    with open(os.path.join(release_dir, "release_manifest.json"), "rb") as fh:
        rm_sha = hashlib.sha256(fh.read()).hexdigest()
    with open(os.path.join(release_dir, "index.json"), encoding="utf-8") as fh:
        idx = json.load(fh)
    scenes = sorted((e["scene_id"], e["fingerprint"]) for e in idx["scenes"] if e["split"] == split)
    materialize_release(release_dir, cache_dir)
    spec = {
        "benchmark": name, "version": version,
        "release": {"name": idx["meta"]["name"], "version": idx["meta"]["version"],
                    "release_manifest_sha256": rm_sha},
        "split": split,
        "scenes": [{"scene_id": s, "fingerprint": f} for s, f in scenes],
        "data_sha256": _tensor_hash(scenes, cache_dir),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(spec, fh, sort_keys=False)
    return spec


def load_benchmark(spec_path: str, release_dir: str, cache_dir: str) -> Dict[str, object]:
    """Verify and load a locked benchmark; returns {scenes, data_sha256, cache_dir}."""
    import yaml
    with open(spec_path, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    verify_benchmark_manifest(os.path.join(release_dir, "release_manifest.json"),
                              spec["release"]["release_manifest_sha256"])
    materialize_release(release_dir, cache_dir)
    scenes = [(e["scene_id"], e["fingerprint"]) for e in spec["scenes"]]
    got = _tensor_hash(scenes, cache_dir)
    if got != spec["data_sha256"]:
        raise BenchmarkIntegrityError(f"data hash {got[:12]}… != locked {spec['data_sha256'][:12]}…")
    return {"scenes": [(os.path.join(cache_dir, s, "scene_manifest.json"), f) for s, f in scenes],
            "data_sha256": got, "cache_dir": cache_dir, "spec": spec}
