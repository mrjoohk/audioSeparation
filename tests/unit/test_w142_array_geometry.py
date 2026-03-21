"""Unit tests for UF-W142: Array Geometry / Error Modeling."""
import sys
from pathlib import Path
import pytest
import numpy as np
from scipy.stats import ks_1samp, norm

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
from simulator.uf.w142_array_geometry import (
    create_array_template,
    perturb_array_positions,
    model_clock_skew,
    export_array_geometry,
)

# ---------------------------------------------------------------------------
# create_array_template
# ---------------------------------------------------------------------------

def test_ula_element_count():
    arr = create_array_template("ULA", n_elements=8, spacing_m=0.05)
    assert arr.nominal_positions.shape == (8, 3)


def test_ula_spacing_accuracy():
    """4-element ULA d=0.05 m → spacing = 0.05 m ± 0.1 mm."""
    arr = create_array_template("ULA", n_elements=4, spacing_m=0.05)
    pos = arr.nominal_positions
    spacings = np.linalg.norm(np.diff(pos, axis=0), axis=1)
    assert np.allclose(spacings, 0.05, atol=1e-4), f"Spacings: {spacings}"


def test_circular_array_radius():
    """Circular 6-element at radius r → all elements equidistant from center."""
    arr = create_array_template("circular", n_elements=6, spacing_m=0.05)
    center = arr.nominal_positions.mean(axis=0)
    radii = np.linalg.norm(arr.nominal_positions - center, axis=1)
    assert np.allclose(radii, radii[0], atol=1e-6), f"Radii not equal: {radii}"


def test_ula_centered_at_origin():
    arr = create_array_template("ULA", n_elements=5, spacing_m=0.1)
    center_x = arr.nominal_positions[:, 0].mean()
    assert abs(center_x) < 1e-9, f"ULA center_x={center_x:.3e} ≠ 0"


# ---------------------------------------------------------------------------
# perturb_array_positions
# ---------------------------------------------------------------------------

def test_perturbation_magnitude():
    """All displacements < 3σ = 6 mm for σ=2 mm."""
    arr = create_array_template("ULA", n_elements=8, spacing_m=0.05)
    sigma = 0.002
    perturbed = perturb_array_positions(arr, sigma_m=sigma, seed=42)
    displacements = np.linalg.norm(
        perturbed.effective_positions - arr.nominal_positions, axis=1
    )
    assert np.all(displacements <= 3 * sigma + 1e-9), \
        f"Max displacement {displacements.max()*1000:.2f} mm exceeds 3σ={3*sigma*1000:.1f} mm"


def test_perturbation_distribution():
    """σ=2 mm, N=100 arrays of 1 element → displacements normally distributed (KS p > 0.05)."""
    arr = create_array_template("ULA", n_elements=1, spacing_m=0.05)
    sigma = 0.002
    x_displacements = []
    for seed in range(100):
        p = perturb_array_positions(arr, sigma_m=sigma, seed=seed)
        x_displacements.append(
            p.effective_positions[0, 0] - arr.nominal_positions[0, 0]
        )
    x_displacements = np.array(x_displacements)
    # KS test against N(0, sigma^2)
    stat, p_val = ks_1samp(x_displacements, norm(0, sigma).cdf)
    assert p_val > 0.05, f"KS test failed p={p_val:.4f} — distribution not Gaussian"


def test_effective_positions_set():
    arr = create_array_template("ULA", n_elements=4, spacing_m=0.05)
    perturbed = perturb_array_positions(arr, sigma_m=0.001, seed=0)
    assert perturbed.effective_positions is not None
    assert perturbed.effective_positions.shape == arr.nominal_positions.shape


# ---------------------------------------------------------------------------
# model_clock_skew
# ---------------------------------------------------------------------------

def test_clock_skew_range():
    """Clock skew must be ≤ 1 sample at Fs=16000."""
    arr = create_array_template("ULA", n_elements=16, spacing_m=0.05)
    arr = perturb_array_positions(arr, sigma_m=0.001, seed=0)
    arr = model_clock_skew(arr, max_skew_samples=1, fs=16000, seed=42)
    assert arr.clock_skew_samples is not None
    assert np.all(np.abs(arr.clock_skew_samples) <= 1), \
        f"Clock skew exceeds ±1 sample: {arr.clock_skew_samples}"


def test_clock_skew_integer_values():
    arr = create_array_template("ULA", n_elements=8, spacing_m=0.05)
    arr = perturb_array_positions(arr, sigma_m=0.001, seed=0)
    arr = model_clock_skew(arr, max_skew_samples=1, fs=16000, seed=1)
    assert arr.clock_skew_samples.dtype in (np.int32, np.int64, int), \
        f"Clock skew dtype {arr.clock_skew_samples.dtype} is not integer"


# ---------------------------------------------------------------------------
# export_array_geometry
# ---------------------------------------------------------------------------

def test_export_creates_file(tmp_path):
    arr = create_array_template("ULA", n_elements=4, spacing_m=0.05)
    arr = perturb_array_positions(arr, sigma_m=0.001, seed=0)
    arr = model_clock_skew(arr, seed=0)
    out = tmp_path / "array.json"
    result = export_array_geometry(arr, str(out))
    assert out.exists()
    assert "nominal_positions" in result
