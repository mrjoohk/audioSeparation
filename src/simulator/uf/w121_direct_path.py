"""
UF-W121: Direct Path Acoustic Propagation
Implements UF-W121-01 through UF-W121-04.

Functions:
    compute_distance_and_delay  (UF-W121-01)
    compute_attenuation         (UF-W121-02)
    compute_doa                 (UF-W121-03)
    compute_air_attenuation     (UF-W121-04)
    build_direct_path           (helper, assembles DirectPath dataclass)
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Path setup so the module is importable regardless of working directory
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parents[3] / "src"))
from simulator.types import (
    OCTAVE_BAND_CENTERS,
    SPEED_OF_SOUND,
    MIN_SOURCE_MIC_DIST_M,
    MAX_SOURCE_MIC_DIST_M,
    DirectPath,
)

# ---------------------------------------------------------------------------
# ISO 9613-1 air absorption coefficients (dB/m) at octave band centres
# ---------------------------------------------------------------------------
_ISO9613_ALPHA: dict[float, float] = {
    125.0: 0.0003,
    250.0: 0.0006,
    500.0: 0.0014,
    1000.0: 0.0038,
    2000.0: 0.0117,
    4000.0: 0.0360,
}

_ISO9613_FREQS = np.array(sorted(_ISO9613_ALPHA.keys()), dtype=np.float64)
_ISO9613_COEFFS = np.array([_ISO9613_ALPHA[f] for f in _ISO9613_FREQS], dtype=np.float64)


# ---------------------------------------------------------------------------
# UF-W121-01
# ---------------------------------------------------------------------------

def compute_distance_and_delay(
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    c: float = SPEED_OF_SOUND,
    fs: int = 16000,
) -> dict:
    """Compute propagation distance, time delay, and sample delay.

    Parameters
    ----------
    src_pos : array_like, shape (3,)
        Source position in world frame (metres).
    mic_pos : array_like, shape (3,)
        Microphone position in world frame (metres).
    c : float
        Speed of sound (m/s).  Default 343.0.
    fs : int
        Sample rate (Hz).  Default 16000.

    Returns
    -------
    dict with keys:
        "distance_m"     – Euclidean distance (float)
        "delay_s"        – propagation delay (float)
        "delay_samples"  – rounded integer sample delay (int)
    """
    src_pos = np.asarray(src_pos, dtype=np.float64)
    mic_pos = np.asarray(mic_pos, dtype=np.float64)

    distance_m = float(np.linalg.norm(src_pos - mic_pos))

    if distance_m < MIN_SOURCE_MIC_DIST_M:
        warnings.warn(
            f"Near-field condition: distance={distance_m:.4f} m < "
            f"{MIN_SOURCE_MIC_DIST_M} m.  Results may be inaccurate.",
            RuntimeWarning,
            stacklevel=2,
        )
    if distance_m > MAX_SOURCE_MIC_DIST_M:
        warnings.warn(
            f"Far-field condition: distance={distance_m:.4f} m > "
            f"{MAX_SOURCE_MIC_DIST_M} m.  Results may be inaccurate.",
            RuntimeWarning,
            stacklevel=2,
        )

    delay_s = distance_m / c
    delay_samples = int(round(delay_s * fs))

    return {
        "distance_m": distance_m,
        "delay_s": delay_s,
        "delay_samples": delay_samples,
    }


# ---------------------------------------------------------------------------
# UF-W121-02
# ---------------------------------------------------------------------------

def compute_attenuation(distance_m: float, ref_distance_m: float = 1.0) -> float:
    """Compute free-field (1/r) amplitude attenuation.

    The result is clamped to [0, 1] so that sub-ref-distance does not
    amplify above unity (near-field cap).

    Parameters
    ----------
    distance_m : float
        Propagation distance (m).
    ref_distance_m : float
        Reference distance at which gain = 1.0.  Default 1.0 m.

    Returns
    -------
    float
        Linear attenuation factor in [0, 1].
    """
    safe_dist = max(float(distance_m), 0.01)
    attenuation = ref_distance_m / safe_dist
    return float(min(max(attenuation, 0.0), 1.0))


# ---------------------------------------------------------------------------
# Helper: quaternion rotation
# ---------------------------------------------------------------------------

def _quat_rotate(quat: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Rotate vector v by unit quaternion quat = (x, y, z, w).

    Uses the formula:  v' = q * [0, v] * q_conj  (Hamilton product).
    """
    x, y, z, w = float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3])
    # Normalise
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-12:
        raise ValueError("Quaternion has near-zero norm; cannot rotate.")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm

    vx, vy, vz = float(v[0]), float(v[1]), float(v[2])

    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)

    # v' = v + w*t + cross(q.xyz, t)
    rx = vx + w * tx + (y * tz - z * ty)
    ry = vy + w * ty + (z * tx - x * tz)
    rz = vz + w * tz + (x * ty - y * tx)

    return np.array([rx, ry, rz], dtype=np.float64)


# ---------------------------------------------------------------------------
# UF-W121-03
# ---------------------------------------------------------------------------

def compute_doa(
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    mic_orientation_quat: Optional[np.ndarray] = None,
) -> dict:
    """Compute Direction-of-Arrival (azimuth + elevation).

    Coordinate convention: Y-up, right-hand.

    World frame:
        az = atan2(dx, dz)  →  [-π, π]
        el = asin(dy)       →  [-π/2, π/2]

    If ``mic_orientation_quat`` is given the direction vector is first
    expressed in the microphone's local frame (inverse rotation applied).

    Parameters
    ----------
    src_pos : array_like, shape (3,)
    mic_pos : array_like, shape (3,)
    mic_orientation_quat : array_like, shape (4,) or None
        Quaternion (x, y, z, w) describing the microphone orientation.
        When provided, the direction is expressed in mic-local frame.

    Returns
    -------
    dict with keys:
        "doa_az_rad"  – azimuth   (float, radians)
        "doa_el_rad"  – elevation (float, radians)

    Raises
    ------
    ValueError
        If src_pos == mic_pos (zero distance).
    """
    src_pos = np.asarray(src_pos, dtype=np.float64)
    mic_pos = np.asarray(mic_pos, dtype=np.float64)

    diff = src_pos - mic_pos
    dist = float(np.linalg.norm(diff))
    if dist < 1e-12:
        raise ValueError(
            "src_pos and mic_pos are identical (zero distance); "
            "cannot compute direction-of-arrival."
        )

    direction = diff / dist  # unit vector

    if mic_orientation_quat is not None:
        quat = np.asarray(mic_orientation_quat, dtype=np.float64)
        # Rotate direction into mic local frame: apply conjugate quaternion
        # q_conj = (-x, -y, -z, w)
        q_conj = np.array([-quat[0], -quat[1], -quat[2], quat[3]], dtype=np.float64)
        direction = _quat_rotate(q_conj, direction)

    az = math.atan2(float(direction[0]), float(direction[2]))
    el = math.asin(float(np.clip(direction[1], -1.0, 1.0)))

    return {"doa_az_rad": az, "doa_el_rad": el}


# ---------------------------------------------------------------------------
# UF-W121-04
# ---------------------------------------------------------------------------

def compute_air_attenuation(
    distance_m: float,
    freq_hz: float,
    velocity_radial_m_s: float = 0.0,
    c: float = SPEED_OF_SOUND,
) -> dict:
    """Compute air absorption (ISO 9613-1) and Doppler shift factor.

    Air absorption coefficient α(f) is log-linearly interpolated between
    the six octave-band values from ISO 9613-1.  Extrapolation is clamped
    to the nearest defined band coefficient.

    Doppler factor = c / (c - v_r) where v_r is the radial velocity of
    the source towards the microphone (positive = approaching).

    Parameters
    ----------
    distance_m : float
        Propagation distance (m).
    freq_hz : float
        Frequency of interest (Hz).  Must be > 0.
    velocity_radial_m_s : float
        Radial velocity of source relative to mic (m/s).  Positive =
        approaching.  Default 0.0.
    c : float
        Speed of sound (m/s).  Default 343.0.

    Returns
    -------
    dict with keys:
        "air_atten_db"    – absorption loss (float, dB ≥ 0)
        "doppler_factor"  – frequency scaling factor (float > 0)
    """
    if freq_hz <= 0.0:
        raise ValueError(f"freq_hz must be positive; got {freq_hz}.")

    # Log-linear interpolation of ISO 9613-1 coefficients
    log_freqs = np.log10(_ISO9613_FREQS)
    log_alpha = np.log10(_ISO9613_COEFFS)
    log_f = math.log10(float(freq_hz))

    # Clamp to defined range
    log_f_clamped = float(np.clip(log_f, log_freqs[0], log_freqs[-1]))
    alpha_db_per_m = float(10.0 ** np.interp(log_f_clamped, log_freqs, log_alpha))

    air_atten_db = alpha_db_per_m * float(distance_m)

    # Doppler
    v_r = float(velocity_radial_m_s)
    if abs(v_r) > 0.1 * c:
        warnings.warn(
            f"Radial velocity |{v_r:.2f}| m/s exceeds 10 % of speed of sound "
            f"({0.1 * c:.1f} m/s).  Doppler formula may be inaccurate.",
            RuntimeWarning,
            stacklevel=2,
        )

    denominator = c - v_r
    if abs(denominator) < 1e-6:
        raise ValueError(
            "Radial velocity equals or exceeds speed of sound; "
            "Doppler formula is singular."
        )
    doppler_factor = c / denominator

    return {"air_atten_db": float(air_atten_db), "doppler_factor": float(doppler_factor)}


# ---------------------------------------------------------------------------
# Helper: assemble DirectPath
# ---------------------------------------------------------------------------

def build_direct_path(
    src_id: str,
    mic_id: str,
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    fs: int,
    c: float = SPEED_OF_SOUND,
    mic_orientation_quat: Optional[np.ndarray] = None,
    velocity_radial: float = 0.0,
    ref_distance_m: float = 1.0,
    freq_hz: float = 1000.0,
) -> DirectPath:
    """Assemble all four UF-W121 sub-functions into a DirectPath dataclass.

    Parameters
    ----------
    src_id : str
        Source identifier.
    mic_id : str
        Microphone/receiver identifier.
    src_pos : array_like, shape (3,)
        Source position (m).
    mic_pos : array_like, shape (3,)
        Microphone position (m).
    fs : int
        Sample rate (Hz).
    c : float
        Speed of sound (m/s).
    mic_orientation_quat : array_like, shape (4,) or None
        Mic orientation quaternion (x,y,z,w).
    velocity_radial : float
        Source radial velocity towards mic (m/s).
    ref_distance_m : float
        Reference distance for 1/r attenuation (m).
    freq_hz : float
        Frequency for air-attenuation computation (Hz).

    Returns
    -------
    DirectPath
    """
    src_pos = np.asarray(src_pos, dtype=np.float64)
    mic_pos = np.asarray(mic_pos, dtype=np.float64)

    dd = compute_distance_and_delay(src_pos, mic_pos, c=c, fs=fs)
    atten = compute_attenuation(dd["distance_m"], ref_distance_m=ref_distance_m)
    doa = compute_doa(src_pos, mic_pos, mic_orientation_quat=mic_orientation_quat)
    air = compute_air_attenuation(
        dd["distance_m"], freq_hz, velocity_radial_m_s=velocity_radial, c=c
    )

    return DirectPath(
        source_id=src_id,
        receiver_id=mic_id,
        distance_m=dd["distance_m"],
        delay_s=dd["delay_s"],
        delay_samples=dd["delay_samples"],
        attenuation_linear=atten,
        doa_az_rad=doa["doa_az_rad"],
        doa_el_rad=doa["doa_el_rad"],
        air_atten_db=air["air_atten_db"],
        doppler_factor=air["doppler_factor"],
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import numpy as np

    src = np.array([1.0, 0.0, 0.0])
    mic = np.array([0.0, 0.0, 0.0])

    dd = compute_distance_and_delay(src, mic, fs=16000)
    print(f"[smoke] distance_and_delay: {dd}")

    atten = compute_attenuation(5.0)
    print(f"[smoke] attenuation at 5 m (ref=1 m): {atten:.4f}  (expected 0.2)")

    doa = compute_doa(np.array([5.0, 0.0, 0.0]), np.array([0.0, 0.0, 0.0]))
    print(f"[smoke] doa: az={math.degrees(doa['doa_az_rad']):.1f}° "
          f"el={math.degrees(doa['doa_el_rad']):.1f}°  (expected az≈90°, el≈0°)")

    air = compute_air_attenuation(10.0, 1000.0)
    print(f"[smoke] air_atten @1 kHz, 10 m: {air['air_atten_db']:.4f} dB  (expected ≈0.038)")

    dp = build_direct_path("src0", "mic0", src, mic, fs=16000)
    print(f"[smoke] DirectPath: {dp}")

    print("[smoke] w121_direct_path OK")
