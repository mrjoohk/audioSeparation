"""Unit tests for UF-W144: Codec/Channel Impairment Modeling."""
import sys
from pathlib import Path
import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
from simulator.uf.w144_codec import (
    apply_bandwidth_limit,
    apply_codec_artifacts,
    apply_packet_loss,
    tag_impairment_conditions,
)

FS = 16000
N = 32000  # 2 seconds


def white_noise(n=N, seed=0):
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def compute_band_energy_db(signal, fs, low_hz, high_hz):
    """Compute energy in [low_hz, high_hz] band via FFT."""
    fft = np.fft.rfft(signal)
    freqs = np.fft.rfftfreq(len(signal), 1.0 / fs)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    energy = np.sum(np.abs(fft[mask]) ** 2)
    return 10 * np.log10(energy + 1e-30)


# ---------------------------------------------------------------------------
# apply_bandwidth_limit
# ---------------------------------------------------------------------------

def test_bandwidth_4khz_stopband():
    """After 4 kHz lowpass, energy above 4.5 kHz < −40 dB relative to passband."""
    sig = white_noise()
    out = apply_bandwidth_limit(sig, bandwidth_hz=4000.0, fs=FS, filter_order=128)

    passband_energy_db = compute_band_energy_db(out, FS, 100, 3500)
    stopband_energy_db = compute_band_energy_db(out, FS, 4500, FS // 2 - 100)
    attenuation = passband_energy_db - stopband_energy_db
    assert attenuation >= 40.0, \
        f"Stopband attenuation = {attenuation:.1f} dB, expected ≥ 40 dB"


def test_bandwidth_output_shape():
    sig = white_noise()
    out = apply_bandwidth_limit(sig, bandwidth_hz=4000.0, fs=FS)
    assert out.shape == sig.shape, "Output shape must match input"


def test_bandwidth_output_float32():
    sig = white_noise()
    out = apply_bandwidth_limit(sig, bandwidth_hz=4000.0, fs=FS)
    assert out.dtype == np.float32


# ---------------------------------------------------------------------------
# apply_codec_artifacts
# ---------------------------------------------------------------------------

def test_codec_changes_signal():
    sig = white_noise()
    out = apply_codec_artifacts(sig, fs=FS, bitrate_kbps=32)
    assert not np.allclose(out, sig), "Codec artifacts had no effect"


def test_codec_output_shape():
    sig = white_noise()
    out = apply_codec_artifacts(sig, fs=FS, bitrate_kbps=32)
    assert out.shape == sig.shape


# ---------------------------------------------------------------------------
# apply_packet_loss
# ---------------------------------------------------------------------------

def test_packet_loss_count_approx():
    """PER=0.1, 100 segments × 20 ms → ~10 ± 5 dropped."""
    n_segments = 100
    seg_ms = 20.0
    sig = white_noise(n=int(n_segments * seg_ms * FS / 1000))
    out, n_dropped, total = apply_packet_loss(
        sig, fs=FS, packet_error_rate=0.1, segment_duration_ms=seg_ms, seed=42
    )
    assert total == n_segments, f"Expected {n_segments} total segments, got {total}"
    assert 5 <= n_dropped <= 25, f"Expected ~10 dropped, got {n_dropped}"


def test_packet_loss_zero_segments():
    """PER=0 → no segments dropped."""
    sig = white_noise()
    out, n_dropped, _ = apply_packet_loss(
        sig, fs=FS, packet_error_rate=0.0, segment_duration_ms=20.0, seed=0
    )
    assert n_dropped == 0
    assert np.allclose(out, sig)


def test_packet_loss_all_dropped():
    """PER=1.0 (explicit stress condition) → all segments zeroed.

    PER is limited to [0, 0.2] by requirement; values above need allow_stress=True
    (see test_packet_loss_invalid_per).  Design doc §8.
    """
    sig = white_noise(n=3200)
    out, n_dropped, total = apply_packet_loss(
        sig, fs=FS, packet_error_rate=1.0, segment_duration_ms=20.0, seed=0,
        allow_stress=True,
    )
    assert n_dropped == total
    assert np.allclose(out, 0.0)


def test_packet_loss_reproducibility():
    """Same seed → same dropped segments."""
    sig = white_noise()
    o1, n1, _ = apply_packet_loss(sig, FS, 0.1, 20.0, seed=99)
    o2, n2, _ = apply_packet_loss(sig, FS, 0.1, 20.0, seed=99)
    assert n1 == n2
    assert np.allclose(o1, o2)


def test_packet_loss_invalid_per():
    """PER > 0.2 → raise ValueError."""
    sig = white_noise()
    with pytest.raises(ValueError):
        apply_packet_loss(sig, FS, packet_error_rate=0.5, segment_duration_ms=20.0, seed=0)


# ---------------------------------------------------------------------------
# tag_impairment_conditions
# ---------------------------------------------------------------------------

def test_tag_includes_type():
    from simulator.types import ImpairmentSpec
    spec = ImpairmentSpec(impairment_type="packet_loss", packet_error_rate=0.05)
    results = {"n_dropped_segments": 3, "total_segments": 50}
    tags = tag_impairment_conditions(spec, results)
    assert "type" in tags
    assert tags["type"] == "packet_loss"
