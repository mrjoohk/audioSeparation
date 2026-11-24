"""
Measured HRTF databases in SOFA format (AES69; e.g. HUTUBS, CC BY 4.0).

A SOFA ``SimpleFreeFieldHRIR`` file is HDF5 with
``Data.IR [M, 2, N]`` (receiver 0 = left ear, 1 = right ear),
``SourcePosition [M, 3]`` (azimuth deg counter-clockwise from the front,
elevation deg, distance) and ``Data.SamplingRate``.

The renderer's per-path receiver contract (receiver_models.binaural_response)
is a ``n_taps`` FIR whose centre tap is the arrival time at the head centre.
Measured HRIRs carry the measurement delay, so each subject is re-centred:
the mean onset of both ears for the frontal direction is moved to the centre
tap, which keeps every interaural time and level difference.

Receiver frame (receiver_models): forward +z, up +y, left ear +x.  A SOFA
direction (az, el) maps to (x, y, z) = (cos el sin az, sin el, cos el cos az).
"""
from __future__ import annotations

import functools
import math
import os
from dataclasses import dataclass

import numpy as np
from scipy.signal import resample_poly


@dataclass(frozen=True)
class HrirSet:
    path: str
    fs: int
    dirs: np.ndarray        # [M, 3] unit vectors in the receiver frame
    left: np.ndarray        # [M, n_taps]
    right: np.ndarray       # [M, n_taps]

    def nearest(self, local_dir: np.ndarray) -> int:
        d = np.asarray(local_dir, float)
        d = d / (np.linalg.norm(d) + 1e-12)
        return int(np.argmax(self.dirs @ d))


def sofa_dirs(src_pos: np.ndarray) -> np.ndarray:
    az = np.radians(src_pos[:, 0])
    el = np.radians(src_pos[:, 1])
    return np.stack([np.cos(el) * np.sin(az), np.sin(el), np.cos(el) * np.cos(az)], axis=1)


def _onset(h: np.ndarray, rel_db: float = -20.0) -> float:
    """First sample above ``rel_db`` of the peak (onset estimate of an HRIR)."""
    a = np.abs(h)
    thr = a.max() * 10 ** (rel_db / 20.0)
    return float(np.argmax(a >= thr))


def centre_hrirs(ir: np.ndarray, dirs: np.ndarray, n_taps: int) -> np.ndarray:
    """Shift all HRIRs of one subject so the frontal mean onset lands on ``n_taps // 2``."""
    front = int(np.argmax(dirs @ np.array([0.0, 0.0, 1.0])))
    t0 = 0.5 * (_onset(ir[front, 0]) + _onset(ir[front, 1]))
    shift = int(round(n_taps // 2 - t0))
    out = np.zeros(ir.shape[:2] + (n_taps,), dtype=np.float64)
    n = ir.shape[2]
    src_lo, dst_lo = max(0, -shift), max(0, shift)
    length = min(n - src_lo, n_taps - dst_lo)
    if length > 0:
        out[:, :, dst_lo:dst_lo + length] = ir[:, :, src_lo:src_lo + length]
    return out


def load_sofa(path: str, fs: int = 16000, n_taps: int = 128) -> HrirSet:
    import h5py
    with h5py.File(path, "r") as f:
        ir = np.asarray(f["Data.IR"], np.float64)               # [M, R, N]
        pos = np.asarray(f["SourcePosition"], np.float64)        # [M, 3]
        sfs = int(np.asarray(f["Data.SamplingRate"]).ravel()[0])
    if ir.ndim != 3 or ir.shape[1] != 2:
        raise ValueError(f"{path}: expected Data.IR [M, 2, N], got {ir.shape}")
    if sfs != fs:
        g = math.gcd(sfs, fs)
        ir = resample_poly(ir, fs // g, sfs // g, axis=2)
    dirs = sofa_dirs(pos)
    ir = centre_hrirs(ir, dirs, n_taps)
    return HrirSet(path=os.path.abspath(path), fs=fs, dirs=dirs, left=ir[:, 0], right=ir[:, 1])


@functools.lru_cache(maxsize=16)
def get_hrir_set(path: str, fs: int = 16000, n_taps: int = 128) -> HrirSet:
    return load_sofa(path, fs, n_taps)
