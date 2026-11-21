"""
W100000 Spatial Simulator — UF-W143 Noise and Gain Modeling
Implements UF-W143-01 through UF-W143-04.

UF-W143-01: add_self_noise
UF-W143-02: apply_gain_agc
UF-W143-03: apply_clipping
UF-W143-04: model_channel_snr
"""
from __future__ import annotations

import math
import os
import sys
import warnings

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

# Physical constraints
NOISE_FLOOR_MIN_DBFS: float = -70.0
NOISE_FLOOR_MAX_DBFS: float = -30.0
GAIN_MIN_DB: float = -20.0
GAIN_MAX_DB: float = 30.0
CLIP_THRESHOLD_DBFS: float = 0.0


# ---------------------------------------------------------------------------
# UF-W143-01: add_self_noise
# ---------------------------------------------------------------------------

def add_self_noise(
    signal: np.ndarray,
    noise_floor_dbfs: float,
    fs: int,
    seed: int = 42,
) -> tuple:
    """
    Add broadband self-noise at the specified noise floor level.

    dBFS follows AES17: a full-scale sine (peak 1.0, RMS 1/sqrt(2)) is 0 dBFS.
    noise_power = 10^(noise_floor_dbfs / 10) / 2
    noise = rng.standard_normal(len(signal)) * sqrt(noise_power)
    noisy = signal + noise
    snr_db = 10*log10(mean(signal²) / mean(noise²))

    Parameters
    ----------
    signal : float32[N]
    noise_floor_dbfs : float
        Noise floor level in dBFS. Clamped to [-70, -30] dBFS.
    fs : int
        Sample rate (unused here, present for API consistency).
    seed : int

    Returns
    -------
    (noisy_signal: float32[N], snr_db: float)
    """
    signal = np.asarray(signal, dtype=np.float32)

    # Validate and clamp noise floor
    if noise_floor_dbfs < NOISE_FLOOR_MIN_DBFS or noise_floor_dbfs > NOISE_FLOOR_MAX_DBFS:
        warnings.warn(
            f"add_self_noise: noise_floor_dbfs={noise_floor_dbfs:.1f} dBFS is outside "
            f"valid range [{NOISE_FLOOR_MIN_DBFS}, {NOISE_FLOOR_MAX_DBFS}]. Clamping.",
            UserWarning,
            stacklevel=2,
        )
        noise_floor_dbfs = float(np.clip(
            noise_floor_dbfs, NOISE_FLOOR_MIN_DBFS, NOISE_FLOOR_MAX_DBFS
        ))

    rng = np.random.default_rng(seed)

    # Noise power relative to 0 dBFS (AES17: full-scale sine RMS = 1/sqrt(2))
    noise_power = 10.0 ** (noise_floor_dbfs / 10.0) / 2.0
    noise = (rng.standard_normal(len(signal)) * math.sqrt(noise_power)).astype(np.float32)

    noisy = signal + noise

    # SNR calculation (avoid log(0))
    signal_power = float(np.mean(signal.astype(np.float64) ** 2))
    noise_power_actual = float(np.mean(noise.astype(np.float64) ** 2))

    if noise_power_actual < 1e-30:
        snr_db = float("inf")
    elif signal_power < 1e-30:
        snr_db = float("-inf")
    else:
        snr_db = 10.0 * math.log10(signal_power / noise_power_actual)

    return (noisy.astype(np.float32), float(snr_db))


# ---------------------------------------------------------------------------
# UF-W143-02: apply_gain_agc
# ---------------------------------------------------------------------------

def apply_gain_agc(
    signal: np.ndarray,
    gain_db: float,
    agc_enabled: bool = False,
    agc_target_dbfs: float = -20.0,
) -> np.ndarray:
    """
    Apply fixed gain and optional AGC (Automatic Gain Control).

    Fixed gain: signal *= 10^(gain_db / 20)
    AGC: if enabled, compute RMS of gained signal and scale to hit agc_target_dbfs.

    Parameters
    ----------
    signal : float32[N]
    gain_db : float
        Fixed gain in dB. Clamped to [-20, +30] dB.
    agc_enabled : bool
    agc_target_dbfs : float
        AGC target level in dBFS (default -20).

    Returns
    -------
    float32[N]
    """
    signal = np.asarray(signal, dtype=np.float32)

    # Clamp gain
    if gain_db < GAIN_MIN_DB or gain_db > GAIN_MAX_DB:
        warnings.warn(
            f"apply_gain_agc: gain_db={gain_db:.1f} dB outside [{GAIN_MIN_DB}, {GAIN_MAX_DB}]. "
            "Clamping.",
            UserWarning,
            stacklevel=2,
        )
        gain_db = float(np.clip(gain_db, GAIN_MIN_DB, GAIN_MAX_DB))

    gain_linear = 10.0 ** (gain_db / 20.0)
    result = (signal * float(gain_linear)).astype(np.float32)

    if agc_enabled:
        rms = float(np.sqrt(np.mean(result.astype(np.float64) ** 2)))
        if rms > 1e-12:
            target_amplitude = 10.0 ** (agc_target_dbfs / 20.0)
            agc_scale = target_amplitude / rms
            result = (result * float(agc_scale)).astype(np.float32)
        else:
            warnings.warn(
                "apply_gain_agc: AGC input signal is silent (RMS ≈ 0). Skipping AGC.",
                UserWarning,
                stacklevel=2,
            )

    return result


# ---------------------------------------------------------------------------
# UF-W143-03: apply_clipping
# ---------------------------------------------------------------------------

def apply_clipping(
    signal: np.ndarray,
    clip_threshold_dbfs: float = 0.0,
) -> tuple:
    """
    Hard-clip a signal at the given threshold.

    clip_level = 10^(clip_threshold_dbfs / 20)
    clipped = np.clip(signal, -clip_level, clip_level)
    n_clipped = count of samples where |signal| > clip_level

    Parameters
    ----------
    signal : float32[N]
    clip_threshold_dbfs : float
        Clip threshold in dBFS (default 0.0 dBFS = amplitude 1.0).

    Returns
    -------
    (clipped: float32[N], clipped_flag: bool, n_clipped_samples: int)
    """
    signal = np.asarray(signal, dtype=np.float32)

    clip_level = float(10.0 ** (clip_threshold_dbfs / 20.0))
    n_clipped = int(np.sum(np.abs(signal) > clip_level))
    clipped = np.clip(signal, -clip_level, clip_level).astype(np.float32)
    clipped_flag = n_clipped > 0

    return (clipped, clipped_flag, n_clipped)


# ---------------------------------------------------------------------------
# UF-W143-04: model_channel_snr
# ---------------------------------------------------------------------------

def model_channel_snr(
    signals: np.ndarray,
    snr_target_db_per_channel: np.ndarray,
    fs: int,
    seed: int = 42,
) -> np.ndarray:
    """
    Add noise to each channel to achieve a target per-channel SNR.

    For each channel c:
      signal_power = mean(signals[c]²)
      noise_power = signal_power / 10^(snr_target[c] / 10)
      noise = N(0, noise_power)
      output[c] = signals[c] + noise

    Parameters
    ----------
    signals : float32[C×N]
    snr_target_db_per_channel : float[C]
        Target SNR in dB for each channel.
    fs : int
        Sample rate (present for API consistency).
    seed : int

    Returns
    -------
    noisy : float32[C×N]
    """
    signals = np.asarray(signals, dtype=np.float32)
    snr_targets = np.asarray(snr_target_db_per_channel, dtype=np.float64)
    C, N = signals.shape

    if len(snr_targets) != C:
        raise ValueError(
            f"model_channel_snr: signals has {C} channels but "
            f"snr_target_db_per_channel has {len(snr_targets)} entries."
        )

    rng = np.random.default_rng(seed)
    noisy = np.empty_like(signals)

    for c in range(C):
        ch_signal = signals[c].astype(np.float64)
        signal_power = float(np.mean(ch_signal ** 2))

        if signal_power < 1e-30:
            # Silent channel: add tiny noise regardless of SNR target
            warnings.warn(
                f"model_channel_snr: channel {c} is silent. "
                "Adding minimal noise.",
                UserWarning,
                stacklevel=2,
            )
            noise_power = 1e-10
        else:
            snr_linear = 10.0 ** (snr_targets[c] / 10.0)
            noise_power = signal_power / snr_linear

        noise = rng.standard_normal(N) * math.sqrt(noise_power)
        noisy[c] = (ch_signal + noise).astype(np.float32)

    return noisy


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W143 smoke test ===")
    fs = 16000
    N = 16000
    t = np.arange(N) / fs

    # add_self_noise: tone at -20 dBFS, noise at -60 dBFS → SNR ≈ 40 dB
    amplitude_20dbfs = 10.0 ** (-20.0 / 20.0)
    signal = (np.sin(2 * np.pi * 1000.0 * t) * amplitude_20dbfs).astype(np.float32)
    noisy, snr = add_self_noise(signal, noise_floor_dbfs=-60.0, fs=fs, seed=42)
    print(f"  add_self_noise: SNR={snr:.2f} dB (expected ~40 dB)")
    assert 35.0 < snr < 45.0, f"SNR out of range: {snr}"
    print("  add_self_noise: OK")

    # apply_gain_agc: +6 dB → amplitude ×~2
    sig_test = np.ones(1000, dtype=np.float32) * 0.1
    gained = apply_gain_agc(sig_test, gain_db=6.0)
    ratio = float(gained[0] / sig_test[0])
    assert abs(ratio - 10.0 ** (6.0 / 20.0)) < 0.01, f"Gain ratio: {ratio}"
    print(f"  apply_gain_agc: OK (×{ratio:.4f})")

    # apply_gain_agc with AGC
    agc_out = apply_gain_agc(signal, gain_db=0.0, agc_enabled=True, agc_target_dbfs=-20.0)
    target_rms = 10.0 ** (-20.0 / 20.0)
    actual_rms = float(np.sqrt(np.mean(agc_out.astype(np.float64) ** 2)))
    assert abs(actual_rms - target_rms) < 0.01, f"AGC RMS: {actual_rms}"
    print(f"  apply_gain_agc AGC: OK (RMS={actual_rms:.4f})")

    # apply_clipping: signal peak at +3 dBFS, clip at 0 dBFS
    peak_amplitude = 10.0 ** (3.0 / 20.0)  # ~1.413
    sig_clip = np.full(100, peak_amplitude, dtype=np.float32)
    clipped, clipped_flag, n_clipped = apply_clipping(sig_clip, clip_threshold_dbfs=0.0)
    assert clipped_flag is True, "Expected clipping flag"
    assert n_clipped == 100, f"Expected 100 clipped samples, got {n_clipped}"
    assert float(np.max(np.abs(clipped))) <= 1.0 + 1e-6
    print(f"  apply_clipping: OK ({n_clipped} samples clipped, max={np.max(np.abs(clipped)):.4f})")

    # model_channel_snr
    C = 3
    sigs = np.random.randn(C, N).astype(np.float32) * 0.1
    snr_targets = np.array([20.0, 30.0, 40.0])
    noisy_ch = model_channel_snr(sigs, snr_targets, fs=fs, seed=42)
    assert noisy_ch.shape == sigs.shape
    print(f"  model_channel_snr: OK (shape={noisy_ch.shape})")

    print("All UF-W143 smoke tests passed.")
