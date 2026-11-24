"""
Experiment manifests (W3 design: data version, environment, seed, checkpoint,
evaluator are bound together so a baseline can be re-traced from scratch).
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def git_state() -> Dict[str, object]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                         stderr=subprocess.DEVNULL).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                                             cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip())
        return {"commit": commit, "dirty": dirty}
    except Exception:
        return {"commit": None, "dirty": None}


def environment() -> Dict[str, str]:
    import scipy
    return {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
            "platform": platform.platform()}


def release_identity(release_dir: str) -> Dict[str, str]:
    """Name, version and hash of a W2 release (hash of its release_manifest.json)."""
    path = os.path.join(release_dir, "release_manifest.json")
    with open(path, "rb") as fh:
        data = fh.read()
    man = json.loads(data)
    return {"name": man["name"], "version": man["version"],
            "release_manifest_sha256": hashlib.sha256(data).hexdigest()}


def write_experiment(path: str, *, kind: str, config: dict, seed: int, data: dict,
                     checkpoint: Optional[dict] = None, metrics: Optional[dict] = None,
                     evaluator: Optional[dict] = None) -> dict:
    exp = {
        "schema_version": "1.0.0",
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "config": config,
        "data": data,
        "checkpoint": checkpoint,
        "metrics": metrics,
        "evaluator": evaluator,
        "code": git_state(),
        "environment": environment(),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(exp, fh, indent=1)
    return exp
