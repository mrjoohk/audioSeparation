"""
Load a rendered scene (manifest schema 2.0.0) into training arrays.

Contract (design §3): mixture [C, T], references [S, C, T], noise [C, T] share one
sample grid whose index 0 is the scene start.  The loader resolves paths
relative to the dataset root, so it does not depend on where the scene was
rendered, and it re-checks checksums, shapes, sample rate and fingerprint.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve

SUPPORTED_SCHEMA = "2.0.0"


class SceneContractError(ValueError):
    """The scene on disk does not satisfy the W1→W3 hand-off contract."""


@dataclass
class SceneBundle:
    scene_id: str
    fs: int
    source_ids: List[str]
    receiver_ids: List[str]
    mixture: np.ndarray            # float32 [C, T]
    references: np.ndarray         # float32 [S, C, T]
    noise: Optional[np.ndarray]    # float32 [C, T]; None for storage_profile "training"
    manifest: dict = field(repr=False)

    @property
    def reference_channel(self) -> int:
        return self.receiver_ids.index(self.manifest["render"]["reference_receiver"])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_scene(
    manifest_path: str,
    expected_fingerprint: Optional[str] = None,
    verify_checksums: bool = True,
) -> SceneBundle:
    """Read a scene and validate it against the hand-off contract."""
    mpath = Path(manifest_path)
    with open(mpath, encoding="utf-8") as fh:
        manifest = json.load(fh)
    if manifest.get("schema_version") != SUPPORTED_SCHEMA:
        raise SceneContractError(
            f"{mpath}: manifest schema {manifest.get('schema_version')!r} is not {SUPPORTED_SCHEMA}"
        )
    if expected_fingerprint is not None and manifest.get("fingerprint") != expected_fingerprint:
        raise SceneContractError(f"{mpath}: fingerprint mismatch")
    if not manifest.get("qc", {}).get("passed", False):
        raise SceneContractError(f"{mpath}: scene did not pass QC")

    root = mpath.parent.parent  # manifest paths are "<scene_id>/<file>"
    fs = int(manifest["render"]["fs"])
    T = int(manifest["render"]["n_samples"])
    src_ids = [s["source_id"] for s in manifest["sources"]]
    rec_ids = [r["receiver_id"] for r in manifest["receivers"]]
    S, C = len(src_ids), len(rec_ids)

    mixture = np.full((C, T), np.nan, dtype=np.float32)
    noise = np.full((C, T), np.nan, dtype=np.float32)
    refs = np.full((S, C, T), np.nan, dtype=np.float32)

    for entry in manifest["files"]:
        role = entry.get("role")
        if role not in ("mixture", "noise", "reference"):
            continue
        fp = root / entry["path"]
        if not fp.exists():
            raise SceneContractError(f"missing file {entry['path']}")
        if verify_checksums and _sha256(fp) != entry["sha256"]:
            raise SceneContractError(f"checksum mismatch {entry['path']}")
        rfs, data = wavfile.read(str(fp))
        if rfs != fs:
            raise SceneContractError(f"{entry['path']}: fs {rfs} != {fs}")
        if data.dtype != np.float32 or data.ndim != 1 or data.shape[0] != T:
            raise SceneContractError(
                f"{entry['path']}: expected float32 [{T}], got {data.dtype} {data.shape}"
            )
        c = rec_ids.index(entry["receiver_id"])
        if role == "mixture":
            mixture[c] = data
        elif role == "noise":
            noise[c] = data
        else:
            refs[src_ids.index(entry["source_id"]), c] = data

    noise_expected = manifest["render"].get("storage_profile", "full") == "full"
    checks = [("mixture", mixture), ("references", refs)] + ([("noise", noise)] if noise_expected else [])
    for name, arr in checks:
        if np.isnan(arr).any():
            raise SceneContractError(f"{mpath}: {name} incomplete or non-finite")
    if not noise_expected:
        noise = None

    return SceneBundle(
        scene_id=manifest["scene_id"], fs=fs, source_ids=src_ids, receiver_ids=rec_ids,
        mixture=mixture, references=refs, noise=noise, manifest=manifest,
    )


def check_label_alignment(
    reference: np.ndarray,
    dry: np.ndarray,
    expected_onset: int,
    fs: int,
    tol_ms: float = 1.0,
) -> Tuple[bool, int, int]:
    """Compare a declared arrival sample with the lag measured by cross-correlation.

    The requirement is alignment error **below** ``tol_ms`` (strict).  At
    16 kHz and 1 ms that is < 16 samples: an error of 15 passes, 16 fails.
    The cross-correlation peak marks the strongest path, so use this on
    direct-dominant references (or on RIRs).

    Returns:
        (ok, measured_lag_samples, error_samples)
    """
    ref = np.asarray(reference, dtype=np.float64)
    d = np.asarray(dry, dtype=np.float64)
    xc = fftconvolve(ref, d[::-1], mode="full")
    lag = int(np.argmax(np.abs(xc))) - (len(d) - 1)
    err = abs(lag - int(expected_onset))
    tol_samples = tol_ms * 1e-3 * fs
    return err < tol_samples, lag, err


def iter_dataset(root: str, verify_checksums: bool = True):
    """Yield SceneBundle for every committed scene under ``root``."""
    for mpath in sorted(Path(root).glob("*/scene_manifest.json")):
        if mpath.parent.name.startswith((".", "_")):
            continue
        yield load_scene(str(mpath), verify_checksums=verify_checksums)
