"""
Receiver models applied per propagation path (audit F-09; REQ-W05).

Directivity and binaural filtering depend on each path's arrival direction,
so they are applied to the direct path and to every image source separately
(the former chain applied one pattern to the summed mixture, which is wrong
for several sources and for reflections).

Receiver frame: the receiver's forward axis is +z rotated by ``yaw_deg`` about
+y (Y-up, right-handed).  For a listener facing +z with +y up, the right ear
points to −x, so the binaural azimuth used by the HRTF model is
``az_hrtf = −atan2(x_local, z_local)`` (positive = right).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Union

import numpy as np

PATTERNS = ("omni", "cardioid", "supercardioid", "hypercardioid", "figure8")
# first-order patterns: g(θ) = a + (1 - a) cos θ
_PATTERN_A = {"omni": 1.0, "cardioid": 0.5, "supercardioid": 0.37, "hypercardioid": 0.25, "figure8": 0.0}

PathResponse = Callable[[np.ndarray], Union[float, np.ndarray]]


def to_local(direction_world: np.ndarray, yaw_deg: float) -> np.ndarray:
    """Rotate a world direction into the receiver frame (yaw about +y)."""
    y = math.radians(yaw_deg)
    c, s = math.cos(y), math.sin(y)
    x, yy, z = direction_world
    # inverse rotation of the receiver (rotate world by -yaw)
    return np.array([c * x - s * z, yy, s * x + c * z])


def pattern_gain(pattern: str, local_dir: np.ndarray) -> float:
    if pattern not in _PATTERN_A:
        raise ValueError(f"unknown pattern {pattern!r}; use one of {PATTERNS}")
    a = _PATTERN_A[pattern]
    d = local_dir / (np.linalg.norm(local_dir) + 1e-12)
    return float(a + (1.0 - a) * d[2])          # cos of angle to forward (+z)


def directivity_response(pattern: str, yaw_deg: float = 0.0) -> Optional[PathResponse]:
    if pattern == "omni":
        return None
    return lambda d: pattern_gain(pattern, to_local(d, yaw_deg))


def hrtf_az_el(local_dir: np.ndarray):
    d = local_dir / (np.linalg.norm(local_dir) + 1e-12)
    az = -math.atan2(d[0], d[2])                # positive = right ear side
    el = math.asin(float(np.clip(d[1], -1, 1)))
    return az, el


def binaural_response(ear: str, yaw_deg: float, fs: int, n_taps: int = 128,
                      hrtf: Optional[dict] = None) -> PathResponse:
    """Per-path FIR for one ear.

    ``hrtf=None`` uses the synthetic spherical-head model; ``hrtf={"sofa": path}``
    uses the nearest measured direction of that SOFA file (simulator.hrtf_db).
    Either way the FIR is zero-latency: the kernel is centred, and the RIR
    builder places its centre at the path arrival time.
    """
    from simulator.uf.w124_rir_rendering import _synthetic_hrtf
    if ear not in ("L", "R"):
        raise ValueError(ear)
    if hrtf and hrtf.get("sofa"):
        from simulator.hrtf_db import get_hrir_set
        db = get_hrir_set(str(hrtf["sofa"]), int(fs), int(n_taps))
        bank = db.left if ear == "L" else db.right

        def resp_db(d):
            return bank[db.nearest(to_local(d, yaw_deg))]
        return resp_db

    def resp(d):
        az, el = hrtf_az_el(to_local(d, yaw_deg))
        left, right = _synthetic_hrtf(az, el, n_taps=n_taps, fs=fs)
        return left if ear == "L" else right
    return resp


@dataclass
class ReceiverModel:
    """What the RIR builder needs for one output channel."""
    path_response: Optional[PathResponse] = None
    tail_salt: str = ""            # decorrelates the late tail between ears
    tail_gain: float = 1.0         # diffuse-field gain of the late tail


def diffuse_gain(pattern: str) -> float:
    """RMS gain of a first-order pattern in a diffuse field (energy average over the sphere)."""
    a = _PATTERN_A[pattern]
    return math.sqrt(a * a + (1 - a) ** 2 / 3.0)
