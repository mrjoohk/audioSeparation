"""
Scene output I/O: audio encoding, checksums, staged/atomic commit, verification.

Design: design_md/W100000/W1_audit_remediation_design.md §3.4, §4.4 (F-01, F-08).

* WAV files are written as IEEE float32 (WAVE_FORMAT_IEEE_FLOAT).  The former
  ``wave``-module writer labelled float bytes as PCM int32, so readers
  reinterpreted the values.
* A scene is written into ``<root>/.staging/<scene_id>-<uuid>/`` and only renamed
  to ``<root>/<scene_id>/`` after QC passes.  Failed scenes are moved to
  ``<root>/_quarantine/<scene_id>/`` with ``qc_failure.json``.
* All manifest paths are relative to the output root, so a dataset can be moved.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.io import wavfile

RENDERER_VERSION = "w1-static_v1/2026.11.21"
MANIFEST_SCHEMA_VERSION_V2 = "2.0.0"
MANIFEST_NAME = "scene_manifest.json"
STAGING_DIRNAME = ".staging"
QUARANTINE_DIRNAME = "_quarantine"
AUDIO_ENCODING = "float32"


class SceneQCError(RuntimeError):
    """Raised when a rendered scene fails an integrity (QC) check."""

    def __init__(self, check: str, message: str, details: Optional[dict] = None):
        self.check = check
        self.details = details or {}
        super().__init__(f"[qc:{check}] {message}")


class UnsupportedProfileError(ValueError):
    """Raised when a config requests features outside the supported render profile."""


# ---------------------------------------------------------------------------
# Audio and checksums
# ---------------------------------------------------------------------------

def write_wav_float32(path: str, data: np.ndarray, fs: int) -> None:
    """Write ``data`` ([T] mono or [T, C]) as IEEE-float32 WAV."""
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim not in (1, 2):
        raise ValueError(f"WAV data must be 1-D or 2-D [T, C], got shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise SceneQCError("finite", f"refusing to write non-finite audio to {path}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, int(fs), arr)


def read_wav(path: str) -> Tuple[int, np.ndarray]:
    """Read a WAV file; returns (fs, data) with data as written (float32 for ours)."""
    fs, data = wavfile.read(path)
    return int(fs), data


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def canonical_json(obj) -> str:
    """Deterministic JSON used for fingerprints (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(path: str, data: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=_json_default)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Staging / commit / quarantine
# ---------------------------------------------------------------------------

class SceneStaging:
    """Write a scene into a private staging directory, then commit atomically.

    Usage::

        st = SceneStaging(root, scene_id)
        st.write_wav("mixture__r0.wav", x, fs)
        ...
        final_dir = st.commit()          # or st.quarantine(check, details)
    """

    def __init__(self, output_root: str, scene_id: str) -> None:
        self.output_root = Path(output_root)
        self.scene_id = scene_id
        self.dir = self.output_root / STAGING_DIRNAME / f"{scene_id}-{uuid.uuid4().hex[:12]}"
        self.dir.mkdir(parents=True, exist_ok=False)
        self.final_dir = self.output_root / scene_id
        self._closed = False

    # --- writing ---------------------------------------------------------
    def path(self, name: str) -> str:
        return str(self.dir / name)

    def rel(self, name: str) -> str:
        """Manifest path of ``name`` relative to the output root (POSIX style)."""
        return f"{self.scene_id}/{name}"

    def write_wav(self, name: str, data: np.ndarray, fs: int) -> str:
        p = self.path(name)
        write_wav_float32(p, data, fs)
        return p

    def write_json(self, name: str, data: dict) -> str:
        p = self.path(name)
        write_json(p, data)
        return p

    def staged_files(self) -> List[str]:
        return sorted(
            str(p.relative_to(self.dir)).replace(os.sep, "/")
            for p in self.dir.rglob("*") if p.is_file()
        )

    # --- finishing -------------------------------------------------------
    def commit(self) -> str:
        """Replace ``<root>/<scene_id>`` with the staged directory."""
        if self._closed:
            raise RuntimeError("staging already closed")
        trash = None
        if self.final_dir.exists():
            trash = self.output_root / STAGING_DIRNAME / f"trash-{self.scene_id}-{uuid.uuid4().hex[:8]}"
            os.replace(self.final_dir, trash)
        os.replace(self.dir, self.final_dir)
        self._closed = True
        if trash is not None:
            shutil.rmtree(trash, ignore_errors=True)
        self._cleanup_staging_root()
        return str(self.final_dir)

    def quarantine(self, check: str, message: str, details: Optional[dict] = None) -> str:
        """Move the staged directory to ``_quarantine/<scene_id>`` with the reason."""
        if self._closed:
            raise RuntimeError("staging already closed")
        write_json(str(self.dir / "qc_failure.json"), {
            "scene_id": self.scene_id,
            "check": check,
            "message": message,
            "details": details or {},
            "renderer_version": RENDERER_VERSION,
            "created_at": now_iso(),
        })
        qdir = self.output_root / QUARANTINE_DIRNAME / self.scene_id
        if qdir.exists():
            shutil.rmtree(qdir, ignore_errors=True)
        qdir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(self.dir, qdir)
        self._closed = True
        self._cleanup_staging_root()
        return str(qdir)

    def discard(self) -> None:
        if not self._closed:
            shutil.rmtree(self.dir, ignore_errors=True)
            self._closed = True
            self._cleanup_staging_root()

    def _cleanup_staging_root(self) -> None:
        root = self.output_root / STAGING_DIRNAME
        try:
            root.rmdir()  # only succeeds when empty
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Verification of committed output
# ---------------------------------------------------------------------------

def manifest_path_for(output_root: str, scene_id: str) -> str:
    return str(Path(output_root) / scene_id / MANIFEST_NAME)


def verify_scene_output(
    output_root: str,
    scene_id: str,
    expected_fingerprint: Optional[str] = None,
    mode: str = "checksum",
) -> Tuple[bool, str]:
    """Check that a committed scene is complete and matches its manifest.

    Args:
        mode: "checksum" (re-hash every file) or "exists" (existence + size only).

    Returns:
        (ok, reason) — reason is "" when ok.
    """
    mpath = Path(manifest_path_for(output_root, scene_id))
    if not mpath.exists():
        return False, "manifest_missing"
    try:
        with open(mpath, encoding="utf-8") as fh:
            manifest = json.load(fh)
    except Exception as exc:  # pragma: no cover - corrupt JSON
        return False, f"manifest_unreadable:{exc}"
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION_V2:
        return False, "manifest_legacy_schema"
    if manifest.get("scene_id") != scene_id:
        return False, "manifest_scene_id_mismatch"
    if expected_fingerprint is not None and manifest.get("fingerprint") != expected_fingerprint:
        return False, "fingerprint_mismatch"
    if not (manifest.get("qc") or {}).get("passed", False):
        return False, "qc_not_passed"
    root = Path(output_root)
    for entry in manifest.get("files", []):
        fp = root / entry["path"]
        if not fp.exists():
            return False, f"file_missing:{entry['path']}"
        if "bytes" in entry and fp.stat().st_size != entry["bytes"]:
            return False, f"file_size_mismatch:{entry['path']}"
        if mode == "checksum" and sha256_file(str(fp)) != entry.get("sha256"):
            return False, f"checksum_mismatch:{entry['path']}"
    return True, ""
