"""
STFT helpers, SRP-PHAT azimuth estimation and delay-and-sum beamforming.

Conventions follow the simulator: Y-up, azimuth az = atan2(dx, dz), so the
unit direction in the horizontal plane is u(az) = [sin az, 0, cos az].
Beamformer outputs are phase-referenced to the reference microphone so they
are time-aligned with the reference channel of the dataset.
"""
from __future__ import annotations

import math
from typing import List, Sequence

import numpy as np
from scipy.signal import istft, stft

C = 343.0
NPERSEG = 512
HOP = 128


def stft_c(x: np.ndarray, fs: int, nperseg: int = NPERSEG, hop: int = HOP) -> np.ndarray:
    """STFT of [..., T] → [..., F, N] (Hann, ``hop`` samples)."""
    _, _, Z = stft(x, fs=fs, nperseg=nperseg, noverlap=nperseg - hop, boundary="zeros", padded=True)
    return Z


def istft_c(Z: np.ndarray, fs: int, length: int, nperseg: int = NPERSEG, hop: int = HOP) -> np.ndarray:
    _, x = istft(Z, fs=fs, nperseg=nperseg, noverlap=nperseg - hop, boundary=True)
    x = np.asarray(x)
    if x.shape[-1] < length:
        pad = [(0, 0)] * (x.ndim - 1) + [(0, length - x.shape[-1])]
        x = np.pad(x, pad)
    return x[..., :length]


def steering_delays(mic_pos: np.ndarray, ref: int, az_deg: np.ndarray) -> np.ndarray:
    """Far-field arrival delays (s) of each mic relative to the reference mic.

    Returns [A, M]; a mic closer to the source (along u) has a negative delay.
    """
    az = np.deg2rad(np.atleast_1d(az_deg))
    u = np.stack([np.sin(az), np.zeros_like(az), np.cos(az)], axis=1)       # [A, 3]
    rel = np.asarray(mic_pos, float) - np.asarray(mic_pos, float)[ref]       # [M, 3]
    return -(u @ rel.T) / C


def srp_phat(X: np.ndarray, fs: int, mic_pos: np.ndarray, ref: int, n_sources: int,
             grid_deg: float = 2.0, min_sep_deg: float = 20.0,
             fmin: float = 200.0, fmax: float = 6000.0) -> List[float]:
    """Estimate ``n_sources`` azimuths (deg) with SRP-PHAT on STFT X [M, F, N]."""
    M, F, _ = X.shape
    if M < 2:
        return [0.0] * n_sources
    freqs = np.linspace(0, fs / 2, F)
    band = (freqs >= fmin) & (freqs <= fmax)
    Xn = X[:, band, :] / (np.abs(X[:, band, :]) + 1e-12)
    grid = np.arange(0.0, 360.0, grid_deg)
    tau = steering_delays(mic_pos, ref, grid)                               # [A, M]
    phase = np.exp(2j * np.pi * freqs[band][None, None, :] * tau[:, :, None])   # [A, M, Fb]
    # Σ_n |Σ_m w X|² = wᴴ R w with the per-bin spatial covariance R_f = Σ_n X Xᴴ
    R = np.einsum("mfn,kfn->fmk", Xn, np.conj(Xn))                            # [Fb, M, M]
    power = np.real(np.einsum("amf,fmk,akf->a", phase, R, np.conj(phase)))
    order = np.argsort(power)[::-1]
    picks: List[float] = []
    for i in order:
        az = float(grid[i])
        if all(min(abs(az - p), 360 - abs(az - p)) >= min_sep_deg for p in picks):
            picks.append(az)
        if len(picks) == n_sources:
            break
    return picks


def delay_and_sum(X: np.ndarray, fs: int, mic_pos: np.ndarray, ref: int, az_deg: float) -> np.ndarray:
    """Delay-and-sum toward ``az_deg``; X [M, F, N] → [F, N], aligned to the reference mic."""
    M, F, _ = X.shape
    freqs = np.linspace(0, fs / 2, F)
    tau = steering_delays(mic_pos, ref, np.array([az_deg]))[0]             # [M]
    w = np.exp(2j * np.pi * freqs[None, :] * tau[:, None]) / M             # [M, F]
    return np.einsum("mf,mfn->fn", w, X)


def directional_feature(X: np.ndarray, fs: int, mic_pos: np.ndarray, ref: int, az_deg: float) -> np.ndarray:
    """Mean over non-reference mics of cos(observed IPD − expected IPD for az) → [F, N] in [-1, 1].

    Close to 1 where the time-frequency bin is dominated by a source from ``az``.
    For a single microphone the feature is all zeros.
    """
    M, F, N = X.shape
    if M < 2:
        return np.zeros((F, N))
    freqs = np.linspace(0, fs / 2, F)
    tau = steering_delays(mic_pos, ref, np.array([az_deg]))[0]
    acc = np.zeros((F, N))
    for m in range(M):
        if m == ref:
            continue
        ipd = np.angle(X[m] * np.conj(X[ref]))
        acc += np.cos(ipd + 2 * np.pi * freqs[:, None] * tau[m])
    return acc / (M - 1)


def azimuth_of(src: Sequence[float], center: Sequence[float]) -> float:
    d = np.asarray(src, float) - np.asarray(center, float)
    return math.degrees(math.atan2(d[0], d[2])) % 360.0
