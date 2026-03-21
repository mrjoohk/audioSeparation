"""Unit tests for UF-W143: Electronic Noise and Gain Modeling."""
import sys
from pathlib import Path
import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
from simulator.uf.w143_noise_gain import (
    add_self_noise,
    apply_gain_agc,
    apply_clipping,
    model_channel_snr,
)

FS = 16000
N = 16000  # 1 second


def sine_signal(freq=1000, amplitude_dbfs=-20.0, n=N, fs=FS):
    """Sine wave at given amplitude in dBFS."""
    amplitude = 10 ** (amplitude_dbfs / 20)
    t = np.arange(n) / fs
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


# ---------------------------------------------------------------------------
# add_self_noise
# ---------------------------------------------------------------------------

def test_snr_accuracy():
    """Signal at -20 dBFS + noise at -60 dBFS → SNR ∈ [38, 42] dB."""
    sig = sine_signal(amplitude_dbfs=-20.0)
    noisy, snr = add_self_noise(sig, noise_floor_dbfs=-60.0, fs=FS, seed=42)
    assert 38.0 <= snr <= 42.0, f"SNR={snr:.2f} dB outside [38, 42]"


def test_noise_output_shape():
    sig = sine_signal()
    noisy, snr = add_self_noise(sig, noise_floor_dbfs=-50.0, fs=FS, seed=0)
    assert noisy.shape == sig.shape


def test_noise_reproducible():
    sig = sine_signal()
    n1, _ = add_self_noise(sig, -50.0, FS, seed=7)
    n2, _ = add_self_noise(sig, -50.0, FS, seed=7)
    assert np.allclose(n1, n2)


def test_noise_changes_signal():
    sig = sine_signal()
    noisy, _ = add_self_noise(sig, -40.0, FS, seed=3)
    assert not np.allclose(noisy, sig), "Noise had no effect on signal"


# ---------------------------------------------------------------------------
# apply_gain_agc
# ---------------------------------------------------------------------------

def test_fixed_gain_6db():
    """+6 dB gain → amplitude roughly doubles."""
    sig = np.ones(N, dtype=np.float32) * 0.5
    out = apply_gain_agc(sig, gain_db=6.0)
    expected = 0.5 * (10 ** (6.0 / 20))
    assert np.allclose(out, expected, rtol=1e-4), f"Expected {expected:.4f}, got {out[0]:.4f}"


def test_agc_hits_target():
    """-20 dBFS target: output RMS ≈ -20 dBFS."""
    sig = sine_signal(amplitude_dbfs=-40.0)  # quiet
    out = apply_gain_agc(sig, gain_db=0.0, agc_enabled=True, agc_target_dbfs=-20.0)
    rms_out = np.sqrt(np.mean(out ** 2))
    rms_out_dbfs = 20 * np.log10(rms_out + 1e-12)
    assert abs(rms_out_dbfs - (-20.0)) < 3.0, \
        f"AGC output RMS = {rms_out_dbfs:.1f} dBFS, expected ≈ -20 dBFS"


# ---------------------------------------------------------------------------
# apply_clipping
# ---------------------------------------------------------------------------

def test_clipping_detection():
    """Signal peak +3 dBFS, clip=0 dBFS → clipped=True, n_clipped > 0."""
    amplitude = 10 ** (3.0 / 20)  # +3 dBFS
    sig = np.array([0.0, amplitude, -amplitude, 0.5], dtype=np.float32)
    clipped, is_clipped, n_clipped = apply_clipping(sig, clip_threshold_dbfs=0.0)
    assert is_clipped is True
    assert n_clipped >= 2, f"Expected ≥2 clipped samples, got {n_clipped}"


def test_clipping_bounds():
    """After clipping, |max| ≤ clip_level."""
    sig = (np.random.default_rng(0).standard_normal(1000) * 2.0).astype(np.float32)
    threshold = 0.0
    clip_level = 10 ** (threshold / 20)
    clipped, _, _ = apply_clipping(sig, clip_threshold_dbfs=threshold)
    assert np.all(np.abs(clipped) <= clip_level + 1e-6), \
        f"Clipped signal exceeds threshold: max={np.max(np.abs(clipped)):.4f}"


def test_no_clipping_passthrough():
    """Signal within threshold → output == input, clipped=False."""
    sig = np.ones(100, dtype=np.float32) * 0.5  # -6 dBFS
    clipped, is_clipped, n_clipped = apply_clipping(sig, clip_threshold_dbfs=0.0)
    assert not is_clipped
    assert n_clipped == 0
    assert np.allclose(clipped, sig)


# ---------------------------------------------------------------------------
# model_channel_snr
# ---------------------------------------------------------------------------

def test_channel_snr_shape():
    C = 4
    signals = np.ones((C, N), dtype=np.float32) * 0.1
    snr_targets = np.array([20.0, 30.0, 10.0, 25.0])
    out = model_channel_snr(signals, snr_targets, FS, seed=0)
    assert out.shape == (C, N)


def test_channel_snr_adds_noise():
    C = 2
    signals = np.ones((C, N), dtype=np.float32) * 0.3
    snr_targets = np.array([20.0, 20.0])
    out = model_channel_snr(signals, snr_targets, FS, seed=0)
    assert not np.allclose(out, signals), "SNR modeling had no effect"
