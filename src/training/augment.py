"""
Device/environment augmentation for robustness (REQ-303).

The same *linear* transform (global gain, spectral tilt, band limit) is applied
to the mixture and to every reference, so the separation target stays an exact
decomposition of the augmented mixture.  The filters are identical for all
channels except a small per-channel gain mismatch, so inter-microphone phase
differences (the spatial cue) are untouched — the physical-validity constraint
of REQ-303.  Additive noise is added to the mixture only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np
from scipy import signal


@dataclass
class AugmentConfig:
    gain_db: Tuple[float, float] = (-6.0, 6.0)
    channel_mismatch_db: float = 1.0
    tilt_db: Tuple[float, float] = (-6.0, 6.0)       # first-order shelf at 1 kHz
    bandlimit_prob: float = 0.3
    bandlimit_hz: Tuple[float, float] = (3400.0, 7000.0)
    noise_prob: float = 0.5
    noise_snr_db: Tuple[float, float] = (10.0, 30.0)


def _tilt_sos(fs: int, tilt_db: float):
    """Low shelf (+tilt/2 below 1 kHz, -tilt/2 above) as a first-order filter."""
    g = 10 ** (-tilt_db / 20.0)          # high-frequency gain relative to DC
    # First-order Butterworth LP + HP sum to exactly 1, so LP + g·HP is a shelf
    # from 1 (DC) to g (Nyquist); the overall gain centres it at ±tilt/2 dB.
    bl, al = signal.butter(1, 1000.0 / (fs / 2), "lowpass")
    bh, ah = signal.butter(1, 1000.0 / (fs / 2), "highpass")
    num = np.polyadd(np.polymul(bl, ah), g * np.polymul(bh, al))
    den = np.polymul(al, ah)
    gain_dc = 10 ** (tilt_db / 40.0)
    return num * gain_dc, den


def sample_params(rng: np.random.Generator, n_ch: int, cfg: AugmentConfig) -> dict:
    return {
        "gain_db": float(rng.uniform(*cfg.gain_db)),
        "mismatch_db": rng.uniform(-cfg.channel_mismatch_db, cfg.channel_mismatch_db, n_ch).tolist(),
        "tilt_db": float(rng.uniform(*cfg.tilt_db)),
        "bandlimit_hz": float(rng.uniform(*cfg.bandlimit_hz)) if rng.random() < cfg.bandlimit_prob else None,
        "noise_snr_db": float(rng.uniform(*cfg.noise_snr_db)) if rng.random() < cfg.noise_prob else None,
        "noise_seed": int(rng.integers(1 << 31)),
    }


def apply_linear(x: np.ndarray, fs: int, p: dict) -> np.ndarray:
    """Linear part of the augmentation; x is [C, T] (or [S, C, T])."""
    y = np.asarray(x, float) * 10 ** (p["gain_db"] / 20.0)
    b, a = _tilt_sos(fs, p["tilt_db"])
    y = signal.lfilter(b, a, y, axis=-1)
    if p["bandlimit_hz"] and p["bandlimit_hz"] < fs / 2 * 0.98:
        sos = signal.butter(6, p["bandlimit_hz"] / (fs / 2), "lowpass", output="sos")
        y = signal.sosfilt(sos, y, axis=-1)
    mm = 10 ** (np.asarray(p["mismatch_db"]) / 20.0)
    return y * mm[:, None] if y.ndim == 2 else y * mm[None, :, None]


def augment_scene(mixture: np.ndarray, references: np.ndarray, fs: int, p: dict):
    """Return (augmented mixture [C,T], augmented references [S,C,T])."""
    mix = apply_linear(mixture, fs, p)
    refs = apply_linear(references, fs, p)
    if p["noise_snr_db"] is not None:
        rng = np.random.default_rng(p["noise_seed"])
        n = rng.standard_normal(mix.shape)
        ps = float(np.mean(mix ** 2))
        n *= np.sqrt(ps / (np.mean(n ** 2) * 10 ** (p["noise_snr_db"] / 10.0)))
        mix = mix + n
    return mix, refs
