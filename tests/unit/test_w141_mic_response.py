"""Unit tests for UF-W141: Microphone Response Modeling."""
import sys
from pathlib import Path
import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
from simulator.types import MicSpec
from simulator.uf.w141_mic_response import (
    apply_frequency_response,
    apply_sensitivity_variation,
    apply_directional_pattern,
    inject_manufacturing_tolerance,
)

FS = 16000
N = 4096
RNG = np.random.default_rng(0)


def make_white_noise(n=N, seed=0):
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


# ---------------------------------------------------------------------------
# apply_directional_pattern
# ---------------------------------------------------------------------------

def test_omni_pattern_all_angles():
    """Omni gain = 1.0 regardless of direction."""
    sig = make_white_noise()
    for az in np.linspace(-np.pi, np.pi, 8):
        gain, _ = apply_directional_pattern(sig, az, 0.0, "omni")
        assert abs(gain - 1.0) < 1e-6, f"Omni gain ≠ 1.0 at az={np.degrees(az):.0f}°"


def test_cardioid_front_gain():
    """Cardioid: az=0 (front) → gain ≈ 1.0."""
    sig = make_white_noise()
    gain, _ = apply_directional_pattern(sig, 0.0, 0.0, "cardioid")
    assert abs(gain - 1.0) < 0.05, f"Cardioid front gain={gain:.3f}, expected ~1.0"


def test_cardioid_rear_gain():
    """Cardioid: az=π (rear) → gain ≈ 0.0."""
    sig = make_white_noise()
    gain, _ = apply_directional_pattern(sig, np.pi, 0.0, "cardioid")
    assert gain < 0.1, f"Cardioid rear gain={gain:.3f}, expected ≈0"


def test_figure8_sides_zero():
    """Figure-8: az=π/2 → gain ≈ 0 (null at 90°)."""
    sig = make_white_noise()
    gain, _ = apply_directional_pattern(sig, np.pi / 2, 0.0, "figure8")
    assert abs(gain) < 0.05, f"Figure-8 side gain={gain:.3f}, expected ≈0"


def test_pattern_output_shape():
    sig = make_white_noise(N)
    _, gained = apply_directional_pattern(sig, 0.0, 0.0, "cardioid")
    assert gained.shape == sig.shape


# ---------------------------------------------------------------------------
# apply_sensitivity_variation
# ---------------------------------------------------------------------------

def test_apply_gain_6db():
    """+ 6 dB → amplitude factor ≈ 2.0 ± 1%."""
    C = 2
    signals = np.ones((C, N), dtype=np.float32)
    sensitivities = np.array([6.0, 0.0])
    out = apply_sensitivity_variation(signals, sensitivities)
    assert abs(out[0, 0] - 2.0) < 0.02, f"Expected ~2.0, got {out[0,0]:.4f}"
    assert abs(out[1, 0] - 1.0) < 1e-5, f"Channel 1 should be unchanged"


def test_sensitivity_applied_per_channel():
    C = 4
    signals = np.ones((C, N), dtype=np.float32)
    gains_db = np.array([0.0, 6.0, -6.0, 12.0])
    out = apply_sensitivity_variation(signals, gains_db)
    expected = 10 ** (gains_db / 20)
    for c in range(C):
        assert abs(out[c, 0] - expected[c]) < 0.01 * expected[c]


# ---------------------------------------------------------------------------
# apply_frequency_response
# ---------------------------------------------------------------------------

def test_freq_response_output_length():
    freq_bins = np.array([100.0, 500.0, 1000.0, 4000.0, 8000.0])
    fr_db = np.zeros(5)  # flat 0 dB
    sig = make_white_noise()
    out = apply_frequency_response(sig, fr_db, freq_bins, FS)
    assert out.shape == sig.shape, "Output length must match input"


def test_flat_response_passthrough():
    """0 dB flat response should not dramatically change signal power."""
    freq_bins = np.linspace(100, FS / 2, 50)
    fr_db = np.zeros(50)
    sig = make_white_noise()
    out = apply_frequency_response(sig, fr_db, freq_bins, FS)
    # Power ratio within 6 dB
    power_in = np.mean(sig ** 2)
    power_out = np.mean(out ** 2)
    ratio_db = 10 * np.log10(power_out / (power_in + 1e-12))
    assert abs(ratio_db) < 6.0, f"Power ratio {ratio_db:.1f} dB — too large for flat response"


# ---------------------------------------------------------------------------
# inject_manufacturing_tolerance
# ---------------------------------------------------------------------------

def test_tolerance_perturbs_sensitivity():
    specs = [
        MicSpec(f"mic{i}", np.zeros(10), np.linspace(100, 8000, 10), "omni", 0.0)
        for i in range(4)
    ]
    perturbed = inject_manufacturing_tolerance(specs, tolerance_sigma=0.5, seed=5)
    sensitivities = [s.sensitivity_db for s in perturbed]
    # Not all should be exactly 0 after perturbation
    assert not all(abs(s) < 1e-9 for s in sensitivities), "Perturbation had no effect"


def test_tolerance_reproducible():
    specs = [MicSpec("m0", np.zeros(5), np.linspace(100, 4000, 5), "omni", 0.0)]
    p1 = inject_manufacturing_tolerance(specs, seed=77)
    p2 = inject_manufacturing_tolerance(specs, seed=77)
    assert abs(p1[0].sensitivity_db - p2[0].sensitivity_db) < 1e-9
