"""
W100000 Spatial Simulator — UF-W142 Microphone Array Geometry
Implements UF-W142-01 through UF-W142-04.

UF-W142-01: create_array_template
UF-W142-02: perturb_array_positions
UF-W142-03: model_clock_skew
UF-W142-04: export_array_geometry
"""
from __future__ import annotations

import copy
import json
import math
import os
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from simulator.types import ArrayConfig


# ---------------------------------------------------------------------------
# Physical constraints
# ---------------------------------------------------------------------------
MAX_ARRAY_PERTURBATION_SIGMA_M: float = 0.005  # 5 mm
MAX_CLOCK_SKEW_SAMPLES: int = 1


# ---------------------------------------------------------------------------
# UF-W142-01: create_array_template
# ---------------------------------------------------------------------------

def create_array_template(
    topology: str,
    n_elements: int,
    spacing_m: float = 0.05,
    center_pos: Optional[np.ndarray] = None,
    array_id: str = "array_0",
) -> ArrayConfig:
    """
    Create an ArrayConfig with nominal element positions.

    Parameters
    ----------
    topology : str
        "ULA"      — Uniform Linear Array along the X axis.
        "circular" — Circular array in the XZ plane.
        "custom"   — All elements co-located at center_pos.
    n_elements : int
        Number of microphone elements.
    spacing_m : float
        Element spacing (ULA) or radius computation parameter (circular).
    center_pos : array[3], optional
        Array center position in world frame. Default [0, 0, 0].
    array_id : str

    Returns
    -------
    ArrayConfig with nominal_positions set (effective_positions = None).
    """
    if center_pos is None:
        center_pos = np.zeros(3, dtype=np.float64)
    else:
        center_pos = np.asarray(center_pos, dtype=np.float64)

    if topology == "ULA":
        # Elements at: x = center[0] + (i - (n-1)/2) * spacing, y=center[1], z=center[2]
        offsets = (np.arange(n_elements, dtype=np.float64) - (n_elements - 1) / 2.0) * spacing_m
        positions = np.zeros((n_elements, 3), dtype=np.float64)
        positions[:, 0] = center_pos[0] + offsets
        positions[:, 1] = center_pos[1]
        positions[:, 2] = center_pos[2]

    elif topology == "circular":
        # Radius derived so that arc length between adjacent elements ≈ spacing_m
        # circumference = n_elements * spacing_m → radius = n_elements * spacing_m / (2π)
        radius = n_elements * spacing_m / (2.0 * math.pi)
        positions = np.zeros((n_elements, 3), dtype=np.float64)
        for i in range(n_elements):
            angle = 2.0 * math.pi * i / n_elements
            positions[i, 0] = center_pos[0] + radius * math.cos(angle)
            positions[i, 1] = center_pos[1]
            positions[i, 2] = center_pos[2] + radius * math.sin(angle)

    elif topology == "custom":
        # All co-located at center; user sets effective_positions manually
        positions = np.tile(center_pos, (n_elements, 1)).astype(np.float64)

    else:
        raise ValueError(
            f"Unknown topology '{topology}'. Choose from: ULA, circular, custom."
        )

    return ArrayConfig(
        array_id=array_id,
        topology=topology,
        nominal_positions=positions,
        effective_positions=None,
        clock_skew_samples=None,
    )


# ---------------------------------------------------------------------------
# UF-W142-02: perturb_array_positions
# ---------------------------------------------------------------------------

def perturb_array_positions(
    array_config: ArrayConfig,
    sigma_m: float = 0.002,
    seed: int = 42,
) -> ArrayConfig:
    """
    Add Gaussian position noise to each array element.

    Noise: N(0, sigma_m²) per axis; clipped to ±3*sigma_m.
    Sets effective_positions in a copy of the ArrayConfig.

    Parameters
    ----------
    array_config : ArrayConfig
    sigma_m : float
        Standard deviation of position perturbation in meters (≤ 5 mm enforced).
    seed : int

    Returns
    -------
    ArrayConfig with effective_positions set.
    """
    if sigma_m > MAX_ARRAY_PERTURBATION_SIGMA_M:
        import warnings
        warnings.warn(
            f"perturb_array_positions: sigma_m={sigma_m*1000:.2f} mm exceeds "
            f"maximum {MAX_ARRAY_PERTURBATION_SIGMA_M*1000:.0f} mm. Clamping.",
            UserWarning,
            stacklevel=2,
        )
        sigma_m = MAX_ARRAY_PERTURBATION_SIGMA_M

    rng = np.random.default_rng(seed)
    nominal = array_config.nominal_positions
    n_elements = nominal.shape[0]

    noise = rng.normal(0.0, sigma_m, size=(n_elements, 3))
    # Clip to ±3σ
    noise = np.clip(noise, -3.0 * sigma_m, 3.0 * sigma_m)

    effective = nominal + noise

    # Return a copy with effective_positions set
    new_config = ArrayConfig(
        array_id=array_config.array_id,
        topology=array_config.topology,
        nominal_positions=nominal.copy(),
        effective_positions=effective.astype(np.float64),
        clock_skew_samples=array_config.clock_skew_samples,
    )
    return new_config


# ---------------------------------------------------------------------------
# UF-W142-03: model_clock_skew
# ---------------------------------------------------------------------------

def model_clock_skew(
    array_config: ArrayConfig,
    max_skew_samples: int = 1,
    fs: int = 16000,
    seed: int = 42,
) -> ArrayConfig:
    """
    Assign random integer clock skew per channel.

    Skew ∈ [-max_skew_samples, +max_skew_samples] (uniform integer).
    Sets clock_skew_samples in the returned ArrayConfig.

    Parameters
    ----------
    array_config : ArrayConfig
    max_skew_samples : int
        Maximum absolute clock skew (≤ MAX_CLOCK_SKEW_SAMPLES enforced).
    fs : int
        Sample rate (logged in stats, not directly used here).
    seed : int

    Returns
    -------
    ArrayConfig with clock_skew_samples set.
    """
    if max_skew_samples > MAX_CLOCK_SKEW_SAMPLES:
        import warnings
        warnings.warn(
            f"model_clock_skew: max_skew_samples={max_skew_samples} exceeds "
            f"limit {MAX_CLOCK_SKEW_SAMPLES}. Clamping.",
            UserWarning,
            stacklevel=2,
        )
        max_skew_samples = MAX_CLOCK_SKEW_SAMPLES

    rng = np.random.default_rng(seed)
    n_elements = array_config.nominal_positions.shape[0]

    # Uniform integer skew in [-max_skew_samples, max_skew_samples]
    skews = rng.integers(
        low=-max_skew_samples,
        high=max_skew_samples + 1,
        size=n_elements,
    ).astype(np.int32)

    new_config = ArrayConfig(
        array_id=array_config.array_id,
        topology=array_config.topology,
        nominal_positions=array_config.nominal_positions.copy(),
        effective_positions=(
            array_config.effective_positions.copy()
            if array_config.effective_positions is not None
            else None
        ),
        clock_skew_samples=skews,
    )
    return new_config


# ---------------------------------------------------------------------------
# UF-W142-04: export_array_geometry
# ---------------------------------------------------------------------------

def export_array_geometry(
    array_config: ArrayConfig,
    output_path: str,
) -> dict:
    """
    Export array geometry to JSON.

    Fields: array_id, topology, nominal_positions, effective_positions,
            clock_skew_samples.

    Returns the dict that was written.
    """
    data = {
        "array_id": array_config.array_id,
        "topology": array_config.topology,
        "n_elements": int(array_config.nominal_positions.shape[0]),
        "nominal_positions": array_config.nominal_positions.tolist(),
        "effective_positions": (
            array_config.effective_positions.tolist()
            if array_config.effective_positions is not None
            else None
        ),
        "clock_skew_samples": (
            array_config.clock_skew_samples.tolist()
            if array_config.clock_skew_samples is not None
            else None
        ),
    }

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return data


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W142 smoke test ===")

    # ULA
    arr_ula = create_array_template("ULA", n_elements=4, spacing_m=0.05)
    assert arr_ula.nominal_positions.shape == (4, 3)
    # Check spacing
    for i in range(3):
        d = float(np.linalg.norm(
            arr_ula.nominal_positions[i + 1] - arr_ula.nominal_positions[i]
        ))
        assert abs(d - 0.05) < 1e-9, f"ULA spacing at gap {i}: {d:.6f}"
    print(f"  ULA: OK, positions={arr_ula.nominal_positions[:, 0]}")

    # Circular
    arr_circ = create_array_template("circular", n_elements=6, spacing_m=0.05)
    assert arr_circ.nominal_positions.shape == (6, 3)
    # All elements should be at same radius
    radius = 6 * 0.05 / (2 * math.pi)
    for pos in arr_circ.nominal_positions:
        r = math.sqrt(pos[0]**2 + pos[2]**2)
        assert abs(r - radius) < 1e-9, f"Circular radius mismatch: {r:.6f} vs {radius:.6f}"
    print(f"  Circular: OK, radius={radius:.4f} m")

    # Custom
    arr_cust = create_array_template("custom", n_elements=3, center_pos=np.array([1.0, 1.0, 1.0]))
    assert arr_cust.nominal_positions.shape == (3, 3)
    assert np.allclose(arr_cust.nominal_positions, [[1, 1, 1]] * 3)
    print("  Custom: OK")

    # perturb_array_positions
    arr_perturbed = perturb_array_positions(arr_ula, sigma_m=0.002, seed=42)
    assert arr_perturbed.effective_positions is not None
    displacements = np.linalg.norm(
        arr_perturbed.effective_positions - arr_ula.nominal_positions, axis=1
    )
    assert np.all(displacements < 3 * 0.002 + 1e-9), f"Displacement exceeds 3σ: {displacements}"
    print(f"  perturb: max displacement={displacements.max()*1000:.3f} mm")

    # model_clock_skew
    arr_skewed = model_clock_skew(arr_perturbed, max_skew_samples=1, fs=16000, seed=42)
    assert arr_skewed.clock_skew_samples is not None
    assert np.all(np.abs(arr_skewed.clock_skew_samples) <= 1)
    print(f"  clock_skew: {arr_skewed.clock_skew_samples}")

    # export
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = tf.name
    data = export_array_geometry(arr_skewed, tmp)
    assert data["n_elements"] == 4
    os.unlink(tmp)
    print("  export: OK")

    print("All UF-W142 smoke tests passed.")
