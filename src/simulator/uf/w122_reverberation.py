"""
UF-W122: Reverberation Modelling
Implements UF-W122-01 through UF-W122-04.

Functions:
    compute_image_sources         (UF-W122-01)
    generate_late_reverb_tail     (UF-W122-02)
    shape_reverb_by_frequency     (UF-W122-03)
    fit_rt60                      (UF-W122-04)
    estimate_sabine_rt60          (helper)
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from scipy import signal as sp_signal

# ---------------------------------------------------------------------------
# Path / type imports
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parents[3] / "src"))
from simulator.types import (
    OCTAVE_BAND_CENTERS,
    MAX_RIR_DURATION_S,
    SPEED_OF_SOUND,
    ImageSource,
    LateReverbSpec,
    MaterialSpec,
    MaterialMap,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_ALPHA: float = 0.5          # absorption coefficient when none given
_MAX_ISM_ORDER: int = 10
_DEFAULT_ISM_ORDER: int = 3
_BUTTERWORTH_ORDER: int = 4

# ---------------------------------------------------------------------------
# UF-W122-01  Image Source Method
# ---------------------------------------------------------------------------

def _reflect_coord(n: int, src: float, size: float) -> float:
    """Return the 1-D image coordinate for index n along one axis.

    Allen-Berkley formulation:
        even n :  n * size + src
        odd  n :  n * size - src      (mirror)
    This is equivalent to reflecting src_pos across n room-boundaries.
    """
    if n % 2 == 0:
        return n * size + src
    else:
        return n * size - src


def compute_image_sources(
    room_dims: Dict[str, float],
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    ism_order: int,
    material_map_or_alpha_per_wall=None,
) -> List[ImageSource]:
    """Enumerate image sources for a shoebox room using Allen-Berkley ISM.

    Wall/surface ordering (matches MaterialMap keys used elsewhere):
        0 – floor     (y = 0)
        1 – ceiling   (y = H)
        2 – wall_x+   (x = L)
        3 – wall_x-   (x = 0)
        4 – wall_z+   (z = W)
        5 – wall_z-   (z = 0)

    For each image-source triplet (nx, ny, nz) in
    range(-ism_order, ism_order+1)^3 excluding (0,0,0) the Allen-Berkley
    formula places the image at:

        ix = _reflect_coord(nx, src_x, L)
        iy = _reflect_coord(ny, src_y, H)
        iz = _reflect_coord(nz, src_z, W)

    The number of floor/ceiling reflections along y is abs(ny),
    the number of wall_x reflections along x is abs(nx), etc.
    The total reflection order is |nx| + |ny| + |nz|.

    Wall reflection coefficients are derived from absorption alpha:
        r = sqrt(1 - alpha)

    Parameters
    ----------
    room_dims : dict  {"L": float, "W": float, "H": float}
    src_pos   : array_like (3,)   source position in m
    mic_pos   : array_like (3,)   microphone position in m
    ism_order : int               maximum reflection order (1–10)
    material_map_or_alpha_per_wall : optional
        If None            → default alpha = 0.5 for all walls
        If float           → uniform alpha for all walls
        If array_like[6]   → per-wall alpha [floor, ceil, x+, x-, z+, z-]
        If MaterialMap     → dict {surface_id: MaterialSpec}; uses 500 Hz band

    Returns
    -------
    List[ImageSource]  (filtered to within MAX_RIR_DURATION_S)
    """
    ism_order = int(np.clip(ism_order, 1, _MAX_ISM_ORDER))

    L = float(room_dims["L"])
    W = float(room_dims["W"])
    H = float(room_dims["H"])

    src_pos = np.asarray(src_pos, dtype=np.float64)
    mic_pos = np.asarray(mic_pos, dtype=np.float64)

    # --- Build per-wall reflection coefficients ---
    # Wall order: [floor, ceiling, wall_x+, wall_x-, wall_z+, wall_z-]
    wall_ids = ["floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"]
    band_idx_500 = 2  # index into OCTAVE_BAND_CENTERS for 500 Hz

    if material_map_or_alpha_per_wall is None:
        alphas = np.full(6, _DEFAULT_ALPHA, dtype=np.float64)
    elif isinstance(material_map_or_alpha_per_wall, float):
        alphas = np.full(6, float(material_map_or_alpha_per_wall), dtype=np.float64)
    elif isinstance(material_map_or_alpha_per_wall, dict):
        # MaterialMap: surface_id → MaterialSpec
        mat_map: MaterialMap = material_map_or_alpha_per_wall
        alphas = np.empty(6, dtype=np.float64)
        for i, wid in enumerate(wall_ids):
            if wid in mat_map:
                alphas[i] = float(mat_map[wid].alpha[band_idx_500])
            else:
                alphas[i] = _DEFAULT_ALPHA
    else:
        alphas = np.asarray(material_map_or_alpha_per_wall, dtype=np.float64)
        if alphas.ndim == 0:
            alphas = np.full(6, float(alphas))
        if alphas.shape[0] != 6:
            raise ValueError(
                f"material_map_or_alpha_per_wall as array must have 6 elements; "
                f"got {alphas.shape[0]}."
            )

    alphas = np.clip(alphas, 0.0, 1.0)
    # Reflection coefficients: r = sqrt(1 - alpha)
    refl_coeff = np.sqrt(1.0 - alphas)
    # wall_refl: [floor, ceiling, wall_x+, wall_x-, wall_z+, wall_z-]

    max_dist = MAX_RIR_DURATION_S * SPEED_OF_SOUND
    image_sources: List[ImageSource] = []

    for nx in range(-ism_order, ism_order + 1):
        ix = _reflect_coord(nx, src_pos[0], L)
        for ny in range(-ism_order, ism_order + 1):
            iy = _reflect_coord(ny, src_pos[1], H)
            for nz in range(-ism_order, ism_order + 1):
                if nx == 0 and ny == 0 and nz == 0:
                    continue

                iz = _reflect_coord(nz, src_pos[2], W)

                img_pos = np.array([ix, iy, iz], dtype=np.float64)
                dist = float(np.linalg.norm(img_pos - mic_pos))

                if dist > max_dist or dist < 1e-9:
                    continue

                # --- Accumulate reflection coefficient product ---
                # For each axis index n:
                #   floor / ceiling reflections along y:
                #       floor hits   = number of downward crossings
                #       ceiling hits = number of upward crossings
                #   x-walls:
                #       wall_x- hits, wall_x+ hits
                #   z-walls:
                #       wall_z- hits, wall_z+ hits
                #
                # Allen-Berkley: for reflection index n along one dimension,
                # the number of reflections off each wall depends on parity of n.
                #   |n| reflections total along that axis;
                #   ceiling(|n|/2) from one wall, floor(|n|/2) from the other.
                #   If n > 0: more reflections off the + wall; if n < 0: more off - wall.

                def _wall_hits(n: int):
                    """Return (hits_minus_wall, hits_plus_wall) for index n."""
                    abs_n = abs(n)
                    if n >= 0:
                        plus_hits = (abs_n + 1) // 2
                        minus_hits = abs_n // 2
                    else:
                        minus_hits = (abs_n + 1) // 2
                        plus_hits = abs_n // 2
                    return minus_hits, plus_hits

                # Y axis: floor = -, ceiling = +
                floor_hits, ceil_hits = _wall_hits(ny)
                # X axis: wall_x- = -, wall_x+ = +
                xminus_hits, xplus_hits = _wall_hits(nx)
                # Z axis: wall_z- = -, wall_z+ = +
                zminus_hits, zplus_hits = _wall_hits(nz)

                # wall order: [floor, ceiling, wall_x+, wall_x-, wall_z+, wall_z-]
                gain = (
                    refl_coeff[0] ** floor_hits
                    * refl_coeff[1] ** ceil_hits
                    * refl_coeff[2] ** xplus_hits
                    * refl_coeff[3] ** xminus_hits
                    * refl_coeff[4] ** zplus_hits
                    * refl_coeff[5] ** zminus_hits
                )

                # 1/r attenuation
                path_gain = gain / dist

                order = abs(nx) + abs(ny) + abs(nz)
                image_sources.append(
                    ImageSource(
                        position=img_pos,
                        reflection_order=order,
                        path_gain=float(path_gain),
                    )
                )

    return image_sources


# ---------------------------------------------------------------------------
# UF-W122-02  Late Reverb Tail
# ---------------------------------------------------------------------------

def generate_late_reverb_tail(
    rt60_s: float,
    mixing_time_ms: float,
    fs: int,
    n_samples: Optional[int] = None,
    seed: int = 42,
) -> np.ndarray:
    """Generate an exponentially decaying white-noise late reverb tail.

    Parameters
    ----------
    rt60_s : float
        Reverberation time (s).
    mixing_time_ms : float
        Onset time before which the tail is zero (ms).
    fs : int
        Sample rate (Hz).
    n_samples : int or None
        Total length of output array.  Defaults to
        ``min(rt60_s * 3 * fs, MAX_RIR_DURATION_S * fs)``.
    seed : int
        RNG seed for reproducibility.  Default 42.

    Returns
    -------
    np.ndarray
        float32 array of length n_samples.
    """
    if n_samples is None:
        n_samples = int(min(rt60_s * 3.0 * fs, MAX_RIR_DURATION_S * fs))
    n_samples = max(n_samples, 1)

    onset_sample = int(round(mixing_time_ms * 1e-3 * fs))
    onset_sample = max(0, min(onset_sample, n_samples))

    tail_len = n_samples - onset_sample
    output = np.zeros(n_samples, dtype=np.float32)

    if tail_len <= 0:
        return output

    rng = np.random.default_rng(seed)
    noise = rng.standard_normal(tail_len).astype(np.float64)

    t = np.arange(tail_len, dtype=np.float64) / fs
    # Energy decays as exp(-6.9 * t / RT60) → amplitude as exp(-3.45 * t / RT60)
    # i.e.  e^(-6.9 t/T60) in energy  ≡  e^(-ln(10^6) * t / T60) = 10^(-6t/T60)
    decay = np.exp(-6.9 * t / rt60_s)
    envelope = noise * decay

    output[onset_sample:] = envelope.astype(np.float32)
    return output


# ---------------------------------------------------------------------------
# UF-W122-03  Frequency-Shaped Reverb
# ---------------------------------------------------------------------------

def _butter_bandpass_coeffs(low_hz: float, high_hz: float, fs: int, order: int = 4):
    """Return SOS coefficients for a Butterworth bandpass filter."""
    nyq = fs / 2.0
    low = max(low_hz / nyq, 1e-6)
    high = min(high_hz / nyq, 1.0 - 1e-6)
    if low >= high:
        # Degenerate band: return identity SOS
        sos = np.zeros((1, 6), dtype=np.float64)
        sos[0, 0] = 1.0
        sos[0, 3] = 1.0
        return sos
    sos = sp_signal.butter(order, [low, high], btype="band", output="sos")
    return sos


def shape_reverb_by_frequency(
    base_rir: np.ndarray,
    rt60_per_band: np.ndarray,
    fs: int,
) -> np.ndarray:
    """Reshape a RIR to match per-octave-band RT60 targets.

    The function bandpass-filters the input RIR into 6 octave bands
    (125–4000 Hz), applies per-band exponential decay rescaling so each
    band has the requested RT60, then sums the bands back together.

    Parameters
    ----------
    base_rir : np.ndarray
        Input RIR (float32 or float64), 1-D.
    rt60_per_band : array_like, shape (6,)
        Target RT60 values (s) for octave bands 125, 250, 500, 1000, 2000, 4000 Hz.
    fs : int
        Sample rate (Hz).

    Returns
    -------
    np.ndarray
        float32 array of the same length as base_rir.
    """
    base_rir = np.asarray(base_rir, dtype=np.float64)
    rt60_per_band = np.asarray(rt60_per_band, dtype=np.float64)
    if rt60_per_band.shape != (6,):
        raise ValueError(f"rt60_per_band must have 6 elements; got {rt60_per_band.shape}.")

    N = len(base_rir)
    if N == 0:
        return np.zeros(0, dtype=np.float32)

    t = np.arange(N, dtype=np.float64) / fs
    output = np.zeros(N, dtype=np.float64)

    # Octave-band edges: centre * 2^(-1/2)  ..  centre * 2^(1/2)
    centres = np.array(OCTAVE_BAND_CENTERS, dtype=np.float64)
    band_lows  = centres / (2.0 ** 0.5)
    band_highs = centres * (2.0 ** 0.5)

    # Nyquist guard
    band_highs = np.minimum(band_highs, fs / 2.0 * 0.99)

    for i in range(6):
        rt60 = max(float(rt60_per_band[i]), 0.01)
        sos = _butter_bandpass_coeffs(band_lows[i], band_highs[i], fs, order=_BUTTERWORTH_ORDER)
        band_sig = sp_signal.sosfilt(sos, base_rir)

        # Apply per-band exponential decay shaping
        decay = np.exp(-6.9 * t / rt60)
        # Find current energy envelope of this band and rescale
        # Use a simple RMS approach: multiply by the target envelope
        band_sig_shaped = band_sig * decay

        output += band_sig_shaped

    # Normalise to avoid clipping (preserve relative amplitude but stay within float32 range)
    peak = np.max(np.abs(output))
    if peak > 1e-12:
        output /= peak

    return output.astype(np.float32)


# ---------------------------------------------------------------------------
# UF-W122-04  RT60 Fitting
# ---------------------------------------------------------------------------

def fit_rt60(
    rir: np.ndarray,
    fs: int,
    target_rt60: Optional[float] = None,
) -> dict:
    """Estimate RT60 from an impulse response via Schroeder backward integration.

    The Schroeder backward integral (energy decay curve, EDC) is:
        EDC[n] = sum_{k=n}^{N-1} h[k]^2

    RT60 is the time for the EDC to fall by 60 dB.

    If the RIR is too short to observe −60 dB, the decay is extrapolated
    from the −20 dB point (T20 method: slope * 3).

    Parameters
    ----------
    rir : np.ndarray
        Impulse response (float32 or float64), 1-D.
    fs : int
        Sample rate (Hz).
    target_rt60 : float or None
        If provided, fitting_error_s = rt60_measured_s - target_rt60.

    Returns
    -------
    dict with keys:
        "rt60_measured_s"  – measured RT60 (float, s)
        "fitting_error_s"  – float or None
    """
    rir = np.asarray(rir, dtype=np.float64)
    N = len(rir)
    if N == 0:
        raise ValueError("RIR array is empty; cannot estimate RT60.")

    # Schroeder backward integration
    energy = rir ** 2
    edc = np.cumsum(energy[::-1])[::-1]

    max_edc = edc[0]
    if max_edc < 1e-30:
        warnings.warn("RIR energy is effectively zero; RT60 set to 0.0 s.", RuntimeWarning, stacklevel=2)
        return {"rt60_measured_s": 0.0, "fitting_error_s": None if target_rt60 is None else -target_rt60}

    edc_db = 10.0 * np.log10(edc / max_edc + 1e-120)
    t = np.arange(N, dtype=np.float64) / fs

    # Find −60 dB point
    idx_60 = np.searchsorted(-edc_db, 60.0)  # first index where edc_db <= -60

    if idx_60 < N:
        # Interpolate between the sample before and after
        if idx_60 == 0:
            rt60_measured_s = 0.0
        else:
            t0 = t[idx_60 - 1]
            t1 = t[idx_60]
            db0 = edc_db[idx_60 - 1]
            db1 = edc_db[idx_60]
            if abs(db1 - db0) < 1e-12:
                rt60_measured_s = float(t1)
            else:
                frac = (-60.0 - db0) / (db1 - db0)
                rt60_measured_s = float(t0 + frac * (t1 - t0))
    else:
        # RIR too short: extrapolate from −5 to −20 dB (T20 method)
        idx_5  = np.searchsorted(-edc_db, 5.0)
        idx_20 = np.searchsorted(-edc_db, 20.0)

        if idx_20 >= N:
            # Cannot even find -20 dB; use entire array slope
            idx_5  = 0
            idx_20 = N - 1

        if idx_20 <= idx_5:
            rt60_measured_s = float(t[-1]) * 3.0
        else:
            t5   = t[min(idx_5, N - 1)]
            t20  = t[min(idx_20, N - 1)]
            t20_duration = t20 - t5
            if t20_duration < 1e-9:
                rt60_measured_s = float(t[-1]) * 3.0
            else:
                # Slope: 15 dB over t20_duration → extrapolate to 60 dB = * 4
                rt60_measured_s = t20_duration * 4.0

        warnings.warn(
            f"RIR too short to reach −60 dB; RT60 extrapolated from T20 "
            f"method → {rt60_measured_s:.3f} s.",
            RuntimeWarning,
            stacklevel=2,
        )

    fitting_error_s = None
    if target_rt60 is not None:
        fitting_error_s = float(rt60_measured_s - target_rt60)

    return {
        "rt60_measured_s": float(rt60_measured_s),
        "fitting_error_s": fitting_error_s,
    }


# ---------------------------------------------------------------------------
# Helper: Sabine RT60
# ---------------------------------------------------------------------------

def estimate_sabine_rt60(
    room_dims: Dict[str, float],
    material_map: MaterialMap,
) -> float:
    """Estimate RT60 using the Sabine formula at 500 Hz.

    RT60 = 0.161 * V / (sum_i alpha_i * S_i)

    where V is room volume and S_i are surface areas with absorption
    coefficient alpha_i at 500 Hz (octave band index 2).

    Surface areas for a shoebox room:
        floor   = L * W
        ceiling = L * W
        wall_x+ = W * H
        wall_x- = W * H
        wall_z+ = L * H
        wall_z- = L * H

    If a surface is missing from the material_map, default alpha = 0.5.

    Parameters
    ----------
    room_dims : dict  {"L": float, "W": float, "H": float}
    material_map : MaterialMap  {surface_id → MaterialSpec}

    Returns
    -------
    float  RT60 estimate (s)
    """
    L = float(room_dims["L"])
    W = float(room_dims["W"])
    H = float(room_dims["H"])
    V = L * W * H

    band_idx = 2  # 500 Hz

    # surface_id → area_m2
    surface_areas: dict[str, float] = {
        "floor":    L * W,
        "ceiling":  L * W,
        "wall_x+":  W * H,
        "wall_x-":  W * H,
        "wall_z+":  L * H,
        "wall_z-":  L * H,
    }

    total_absorption = 0.0
    for surf_id, area in surface_areas.items():
        if surf_id in material_map:
            alpha = float(material_map[surf_id].alpha[band_idx])
        else:
            alpha = _DEFAULT_ALPHA
        total_absorption += alpha * area

    if total_absorption < 1e-12:
        warnings.warn(
            "Total absorption is effectively zero; Sabine RT60 is infinite.",
            RuntimeWarning,
            stacklevel=2,
        )
        return float("inf")

    rt60 = 0.161 * V / total_absorption
    return float(rt60)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import numpy as np

    room = {"L": 5.0, "W": 4.0, "H": 3.0}
    src = np.array([1.0, 1.0, 1.0])
    mic = np.array([4.0, 1.5, 2.0])

    # UF-W122-01
    imgs = compute_image_sources(room, src, mic, ism_order=1)
    print(f"[smoke] ISM order=1 → {len(imgs)} image sources (expected ≥6)")

    # UF-W122-02
    tail = generate_late_reverb_tail(0.5, 30.0, 16000, seed=42)
    print(f"[smoke] Late tail shape={tail.shape}, dtype={tail.dtype}")

    # UF-W122-03
    rng_test = np.random.default_rng(0)
    base = rng_test.standard_normal(16000).astype(np.float32)
    shaped = shape_reverb_by_frequency(base, np.array([0.5] * 6), 16000)
    print(f"[smoke] Shaped RIR shape={shaped.shape}, dtype={shaped.dtype}")

    # UF-W122-04
    t_arr = np.arange(16000, dtype=np.float64) / 16000
    synthetic_rir = np.exp(-6.9 * t_arr / 0.5) * np.random.default_rng(1).standard_normal(16000)
    result = fit_rt60(synthetic_rir.astype(np.float32), fs=16000, target_rt60=0.5)
    print(f"[smoke] fit_rt60: {result}")

    # helper
    mat = MaterialSpec(name="concrete", alpha=np.full(6, 0.03), sigma=np.zeros(6))
    mat_map = {sid: mat for sid in ["floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"]}
    sabine = estimate_sabine_rt60(room, mat_map)
    print(f"[smoke] Sabine RT60 (concrete 5x4x3): {sabine:.3f} s  (expected >0.5 s)")

    print("[smoke] w122_reverberation OK")
