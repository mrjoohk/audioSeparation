"""
W100000 Spatial Simulator — UF-W141 Microphone Response Modeling
Implements UF-W141-01 through UF-W141-04.

UF-W141-01: apply_frequency_response
UF-W141-02: apply_sensitivity_variation
UF-W141-03: apply_directional_pattern
UF-W141-04: inject_manufacturing_tolerance
"""
from __future__ import annotations

import copy
import math
import os
import sys
import warnings
from typing import List

import numpy as np
from scipy.signal import firwin2, fftconvolve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from simulator.types import MicSpec


# ---------------------------------------------------------------------------
# UF-W141-01: apply_frequency_response
# ---------------------------------------------------------------------------

def apply_frequency_response(
    signal: np.ndarray,
    freq_response_db: np.ndarray,
    freq_bins_hz: np.ndarray,
    fs: int,
    n_taps: int = 511,
) -> np.ndarray:
    """
    Apply a frequency-dependent response (in dB) to a signal via FIR filtering.

    The FIR filter is designed using frequency sampling (scipy.signal.firwin2).
    The filter is applied via fftconvolve; output is truncated to the original
    signal length.

    Parameters
    ----------
    signal : float32[N]
    freq_response_db : float[F]
        Target frequency response in dB at the given freq_bins_hz.
    freq_bins_hz : float[F]
        Frequency bins in Hz. Must include 0 Hz and fs/2 Hz (or be interpolated).
    fs : int
        Sample rate.
    n_taps : int
        Number of FIR filter taps (odd preferred for linear phase).

    Returns
    -------
    float32[N]  — same length as input signal
    """
    signal = np.asarray(signal, dtype=np.float32)
    freq_response_db = np.asarray(freq_response_db, dtype=np.float64)
    freq_bins_hz = np.asarray(freq_bins_hz, dtype=np.float64)
    N = len(signal)

    # Ensure odd number of taps for Type I FIR (linear phase)
    if n_taps % 2 == 0:
        n_taps += 1

    # Normalize frequencies to [0, 1] for firwin2 (1.0 = Nyquist = fs/2)
    nyquist = fs / 2.0

    # Build frequency array including 0 and 1 (Nyquist)
    freqs_norm = freq_bins_hz / nyquist
    gains_linear = 10.0 ** (freq_response_db / 20.0)

    # Ensure endpoints 0.0 and 1.0 are present; interpolate if needed
    freqs_full = np.copy(freqs_norm)
    gains_full = np.copy(gains_linear)

    if freqs_full[0] > 0.0:
        # Prepend 0.0 with same gain as first bin
        freqs_full = np.concatenate([[0.0], freqs_full])
        gains_full = np.concatenate([[gains_full[0]], gains_full])

    if freqs_full[-1] < 1.0:
        # Append 1.0 with same gain as last bin
        freqs_full = np.concatenate([freqs_full, [1.0]])
        gains_full = np.concatenate([gains_full, [gains_full[-1]]])

    # Clip normalized frequencies to [0, 1]
    freqs_full = np.clip(freqs_full, 0.0, 1.0)
    # Ensure monotonically increasing (firwin2 requirement)
    sort_idx = np.argsort(freqs_full)
    freqs_full = freqs_full[sort_idx]
    gains_full = gains_full[sort_idx]

    # Remove duplicate frequencies
    unique_mask = np.concatenate([[True], np.diff(freqs_full) > 1e-10])
    freqs_full = freqs_full[unique_mask]
    gains_full = gains_full[unique_mask]

    # Design FIR filter via frequency sampling
    try:
        fir_coeffs = firwin2(n_taps, freqs_full, gains_full)
    except Exception as exc:
        warnings.warn(
            f"apply_frequency_response: firwin2 failed ({exc}). "
            "Falling back to identity filter.",
            UserWarning,
            stacklevel=2,
        )
        fir_coeffs = np.zeros(n_taps, dtype=np.float64)
        fir_coeffs[n_taps // 2] = 1.0

    fir_coeffs = fir_coeffs.astype(np.float32)

    # Apply via fftconvolve
    filtered = fftconvolve(signal, fir_coeffs)
    # Truncate/trim to original length
    filtered = filtered[:N].astype(np.float32)

    return filtered


# ---------------------------------------------------------------------------
# UF-W141-02: apply_sensitivity_variation
# ---------------------------------------------------------------------------

def apply_sensitivity_variation(
    signals: np.ndarray,
    sensitivities_db: np.ndarray,
) -> np.ndarray:
    """
    Apply per-channel sensitivity gain to a multi-channel signal array.

    Parameters
    ----------
    signals : float32[C×N]
    sensitivities_db : float[C]
        Sensitivity in dB for each channel.

    Returns
    -------
    float32[C×N]
    """
    signals = np.asarray(signals, dtype=np.float32)
    sensitivities_db = np.asarray(sensitivities_db, dtype=np.float64)

    C = signals.shape[0]
    if len(sensitivities_db) != C:
        raise ValueError(
            f"apply_sensitivity_variation: signals has {C} channels but "
            f"sensitivities_db has {len(sensitivities_db)} entries."
        )

    result = signals.copy()
    for c in range(C):
        gain_linear = 10.0 ** (sensitivities_db[c] / 20.0)
        result[c] *= float(gain_linear)

    return result


# ---------------------------------------------------------------------------
# UF-W141-03: apply_directional_pattern
# ---------------------------------------------------------------------------

def apply_directional_pattern(
    signal: np.ndarray,
    doa_az_rad: float,
    doa_el_rad: float,
    pattern_type: str = "cardioid",
) -> tuple:
    """
    Apply a directional pickup pattern gain to a signal.

    Patterns (simplified 2D, azimuth-dependent):
      "omni"         : gain = 1.0
      "cardioid"     : gain = 0.5 * (1 + cos(az))
      "supercardioid": gain = 0.25 + 0.75*cos(az)
      "figure8"      : gain = |cos(az)|

    Parameters
    ----------
    signal : float32[N]
    doa_az_rad : float
        Direction-of-arrival azimuth in radians (0 = front).
    doa_el_rad : float
        Direction-of-arrival elevation in radians (not used in 2D patterns).
    pattern_type : str

    Returns
    -------
    (pattern_gain: float, gained_signal: float32[N])
    """
    signal = np.asarray(signal, dtype=np.float32)
    az = float(doa_az_rad)

    if pattern_type == "omni":
        gain = 1.0
    elif pattern_type == "cardioid":
        gain = 0.5 * (1.0 + math.cos(az))
    elif pattern_type == "supercardioid":
        gain = 0.25 + 0.75 * math.cos(az)
    elif pattern_type == "figure8":
        gain = abs(math.cos(az))
    else:
        raise ValueError(
            f"Unknown pattern_type '{pattern_type}'. "
            "Choose from: omni, cardioid, supercardioid, figure8."
        )

    # Ensure non-negative gain
    gain = max(0.0, gain)

    return (float(gain), (signal * float(gain)).astype(np.float32))


# ---------------------------------------------------------------------------
# UF-W141-04: inject_manufacturing_tolerance
# ---------------------------------------------------------------------------

def inject_manufacturing_tolerance(
    mic_specs: List[MicSpec],
    tolerance_sigma: float = 0.5,
    seed: int = 42,
) -> List[MicSpec]:
    """
    Perturb microphone specifications to simulate manufacturing variation.

    For each MicSpec:
      - Perturb sensitivity_db by N(0, tolerance_sigma²)
      - Perturb freq_response_db by a random curve N(0, 1 dB) per frequency bin

    Parameters
    ----------
    mic_specs : List[MicSpec]
    tolerance_sigma : float
        Standard deviation for sensitivity perturbation (dB).
    seed : int

    Returns
    -------
    List[MicSpec]  — new list of perturbed MicSpec (originals unchanged)
    """
    rng = np.random.default_rng(seed)
    perturbed: List[MicSpec] = []

    for spec in mic_specs:
        # Deep copy to avoid mutating originals
        new_spec = copy.deepcopy(spec)

        # Perturb sensitivity
        delta_sensitivity = float(rng.normal(0.0, tolerance_sigma))
        new_spec.sensitivity_db = spec.sensitivity_db + delta_sensitivity

        # Perturb freq_response_db with random curve (1 dB std per bin)
        n_bins = len(spec.freq_response_db)
        delta_response = rng.normal(0.0, 1.0, size=n_bins)
        new_spec.freq_response_db = (spec.freq_response_db + delta_response).astype(
            spec.freq_response_db.dtype
        )

        perturbed.append(new_spec)

    return perturbed


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W141 smoke test ===")
    fs = 16000
    N = 4000
    t = np.arange(N) / fs

    # apply_frequency_response: flat 0 dB → should pass through signal mostly unchanged
    signal = (np.sin(2 * np.pi * 1000.0 * t) * 0.5).astype(np.float32)
    freq_bins = np.array([0.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0])
    freq_resp_db = np.zeros(len(freq_bins))
    filtered = apply_frequency_response(signal, freq_resp_db, freq_bins, fs)
    assert filtered.shape == signal.shape, "Output shape mismatch"
    assert filtered.dtype == np.float32
    print(f"  apply_frequency_response: OK (input RMS={np.sqrt(np.mean(signal**2)):.4f}, "
          f"output RMS={np.sqrt(np.mean(filtered**2)):.4f})")

    # apply_sensitivity_variation
    C = 4
    signals_4ch = np.random.randn(C, N).astype(np.float32) * 0.1
    sens_db = np.array([0.0, 6.0, -6.0, 0.0])
    gained = apply_sensitivity_variation(signals_4ch, sens_db)
    # Channel 1 should be ~2x, channel 2 should be ~0.5x
    ratio_ch1 = float(np.std(gained[1]) / np.std(signals_4ch[1]))
    ratio_ch2 = float(np.std(gained[2]) / np.std(signals_4ch[2]))
    assert abs(ratio_ch1 - 2.0) < 0.05, f"Ch1 gain ratio: {ratio_ch1}"
    assert abs(ratio_ch2 - 0.5) < 0.05, f"Ch2 gain ratio: {ratio_ch2}"
    print(f"  apply_sensitivity_variation: OK (ch1 ×{ratio_ch1:.3f}, ch2 ×{ratio_ch2:.3f})")

    # apply_directional_pattern
    sig1d = np.ones(100, dtype=np.float32)
    gain_omni, _ = apply_directional_pattern(sig1d, 0.0, 0.0, "omni")
    assert gain_omni == 1.0, f"Omni gain should be 1.0, got {gain_omni}"

    gain_card_front, _ = apply_directional_pattern(sig1d, 0.0, 0.0, "cardioid")
    gain_card_rear, _ = apply_directional_pattern(sig1d, math.pi, 0.0, "cardioid")
    assert abs(gain_card_front - 1.0) < 0.001, f"Cardioid front={gain_card_front}"
    assert abs(gain_card_rear - 0.0) < 0.001, f"Cardioid rear={gain_card_rear}"
    print(f"  apply_directional_pattern: OK (cardioid front={gain_card_front:.3f}, rear={gain_card_rear:.3f})")

    # inject_manufacturing_tolerance
    spec = MicSpec(
        mic_id="m0",
        freq_response_db=np.zeros(6),
        freq_bins_hz=np.array([125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0]),
        pattern_type="cardioid",
        sensitivity_db=0.0,
    )
    perturbed = inject_manufacturing_tolerance([spec, spec], tolerance_sigma=0.5, seed=42)
    assert len(perturbed) == 2
    # Sensitivity should differ from original
    assert perturbed[0].sensitivity_db != spec.sensitivity_db
    print(f"  inject_manufacturing_tolerance: OK "
          f"(sens {spec.sensitivity_db:.2f} → {perturbed[0].sensitivity_db:.4f} dB)")

    print("All UF-W141 smoke tests passed.")
