"""
W100000 Spatial Simulator — UF-W112 Material Database
Implements UF-W112-01 through UF-W112-04.

UF-W112-01: MaterialDB singleton (register, get)
UF-W112-02: assign_materials
UF-W112-03: stochastic_material_variation
UF-W112-04: export_material_map
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

import sys
import os

# Ensure 'src/' is on sys.path so 'simulator.types' is importable.
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from simulator.types import MaterialMap, MaterialSpec

# ---------------------------------------------------------------------------
# Standard material library
# ---------------------------------------------------------------------------

# Absorption coefficients per octave band:
#   125 Hz, 250 Hz, 500 Hz, 1000 Hz, 2000 Hz, 4000 Hz
_STANDARD_MATERIALS: dict = {
    "concrete":      [0.02, 0.02, 0.03, 0.04, 0.05, 0.05],
    "brick":         [0.03, 0.03, 0.03, 0.04, 0.05, 0.07],
    "carpet":        [0.02, 0.06, 0.14, 0.37, 0.60, 0.65],
    "glass":         [0.35, 0.25, 0.18, 0.12, 0.07, 0.04],
    "wood":          [0.15, 0.11, 0.10, 0.07, 0.06, 0.07],
    "acoustic_tile": [0.15, 0.25, 0.50, 0.80, 0.90, 0.80],
    "default":       [0.10, 0.10, 0.10, 0.10, 0.10, 0.10],
    "anechoic":      [1.00, 1.00, 1.00, 1.00, 1.00, 1.00],   # fully absorbing (tests, REQ-W04)
}

_STANDARD_SIGMA: list = [0.05] * 6


# ---------------------------------------------------------------------------
# UF-W112-01: MaterialDB singleton
# ---------------------------------------------------------------------------

class MaterialDB:
    """
    Singleton dictionary mapping material name → MaterialSpec.

    Usage
    -----
    db = MaterialDB.instance()   # obtain or create the global singleton
    spec = db.get("concrete")
    db.register("custom", alpha=[...], sigma=[...])
    """

    _instance: Optional["MaterialDB"] = None

    def __init__(self) -> None:
        self._db: Dict[str, MaterialSpec] = {}
        self._populate_standard_materials()

    @classmethod
    def instance(cls) -> "MaterialDB":
        """Return (or create) the global singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Destroy the singleton (useful in unit tests for isolation)."""
        cls._instance = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _populate_standard_materials(self) -> None:
        """Pre-populate with standard acoustic materials (no warnings issued)."""
        for name, alpha_vals in _STANDARD_MATERIALS.items():
            spec = MaterialSpec(
                name=name,
                alpha=np.array(alpha_vals, dtype=np.float64),
                sigma=np.array(_STANDARD_SIGMA, dtype=np.float64),
            )
            self._db[name] = spec

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        alpha,
        sigma,
    ) -> MaterialSpec:
        """
        Register a new material in the database.

        Parameters
        ----------
        name : str
            Unique material identifier. Must be non-empty.
        alpha : array-like of shape (6,)
            Absorption coefficients per octave band. Clamped to [0, 1].
        sigma : array-like of shape (6,)
            Scattering coefficients per octave band. Clamped to [0, 1].

        Returns
        -------
        MaterialSpec

        Raises
        ------
        ValueError
            If name is empty, or alpha/sigma do not have 6 elements.
        UserWarning
            If name already exists in the database (value is overwritten).
        """
        if not name:
            raise ValueError("Material name must be a non-empty string.")

        alpha_arr = np.asarray(alpha, dtype=np.float64)
        sigma_arr = np.asarray(sigma, dtype=np.float64)

        if alpha_arr.shape != (6,):
            raise ValueError(
                f"alpha must have exactly 6 octave-band values; got shape {alpha_arr.shape}."
            )
        if sigma_arr.shape != (6,):
            raise ValueError(
                f"sigma must have exactly 6 octave-band values; got shape {sigma_arr.shape}."
            )

        # Clamp to [0, 1]
        alpha_arr = np.clip(alpha_arr, 0.0, 1.0)
        sigma_arr = np.clip(sigma_arr, 0.0, 1.0)

        if name in self._db:
            warnings.warn(
                f"Material '{name}' is already registered; overwriting.",
                UserWarning,
                stacklevel=2,
            )

        spec = MaterialSpec(name=name, alpha=alpha_arr, sigma=sigma_arr)
        self._db[name] = spec
        return spec

    def get(self, name: str) -> MaterialSpec:
        """
        Retrieve a material by name.

        Raises
        ------
        KeyError
            If name is not registered.
        """
        if name not in self._db:
            raise KeyError(
                f"Material '{name}' is not registered in MaterialDB. "
                f"Available: {sorted(self._db.keys())}"
            )
        return self._db[name]

    def __contains__(self, name: str) -> bool:
        return name in self._db

    def __len__(self) -> int:
        return len(self._db)

    def keys(self):
        return self._db.keys()


# ---------------------------------------------------------------------------
# UF-W112-02: assign_materials
# ---------------------------------------------------------------------------

def assign_materials(
    surface_ids: List[str],
    material_assignments: Dict[str, str],
    db: MaterialDB,
) -> MaterialMap:
    """
    Build a MaterialMap (surface_id → MaterialSpec) from an assignments dict.

    Parameters
    ----------
    surface_ids : list of str
        IDs of all surfaces in the room.
    material_assignments : dict {surface_id → material_name}
        Desired material for each surface.  Surfaces missing from this dict
        fall back to "default".
    db : MaterialDB
        The material database to look up from.

    Returns
    -------
    MaterialMap

    Warns
    -----
    UserWarning if a material_name is not found in the DB (falls back to "default").
    """
    material_map: MaterialMap = {}

    for sid in surface_ids:
        mat_name = material_assignments.get(sid, "default")
        if mat_name not in db:
            warnings.warn(
                f"Material '{mat_name}' for surface '{sid}' is not in MaterialDB; "
                f"falling back to 'default'.",
                UserWarning,
                stacklevel=2,
            )
            mat_name = "default"
        material_map[sid] = db.get(mat_name)

    return material_map


# ---------------------------------------------------------------------------
# UF-W112-03: stochastic_material_variation
# ---------------------------------------------------------------------------

def stochastic_material_variation(
    base_spec: MaterialSpec,
    variation_sigma: float = 0.05,
    seed: int = 42,
) -> MaterialSpec:
    """
    Generate a perturbed copy of a MaterialSpec via Gaussian noise.

    Parameters
    ----------
    base_spec : MaterialSpec
        Reference material to perturb.
    variation_sigma : float
        Standard deviation of per-band Gaussian noise applied to alpha.
    seed : int
        RNG seed for reproducibility. Must not be None.

    Returns
    -------
    MaterialSpec with perturbed alpha clipped to [0, 1]; sigma is unchanged.

    Raises
    ------
    ValueError
        If seed is None.
    """
    if seed is None:
        raise ValueError(
            "seed must be an integer; None is not allowed for stochastic_material_variation."
        )

    rng = np.random.default_rng(int(seed))
    noise = rng.normal(loc=0.0, scale=variation_sigma, size=6)
    perturbed_alpha = np.clip(base_spec.alpha + noise, 0.0, 1.0)

    return MaterialSpec(
        name=base_spec.name + "_varied",
        alpha=perturbed_alpha,
        sigma=base_spec.sigma.copy(),
    )


# ---------------------------------------------------------------------------
# UF-W112-04: export_material_map
# ---------------------------------------------------------------------------

def export_material_map(material_map: MaterialMap, output_path: str) -> dict:
    """
    Serialize a MaterialMap to a JSON file.

    Parameters
    ----------
    material_map : MaterialMap
        Dict {surface_id → MaterialSpec}.
    output_path : str
        Destination file path.  Parent directories are created if needed.

    Returns
    -------
    dict
        The serialised representation (also written to the file with indent=2).
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    serialized: dict = {}
    for surface_id, spec in material_map.items():
        serialized[surface_id] = {
            "name":  spec.name,
            "alpha": spec.alpha.tolist(),
            "sigma": spec.sigma.tolist(),
        }

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(serialized, fh, indent=2)

    return serialized


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("=== UF-W112 smoke test ===")

    # 1. Singleton access
    db = MaterialDB.instance()
    print(f"Pre-populated materials: {sorted(db.keys())}")
    assert len(db) == len(_STANDARD_MATERIALS)

    # 2. get standard material
    concrete = db.get("concrete")
    print(f"concrete alpha: {concrete.alpha}")

    # 3. register new material
    new_mat = db.register(
        "test_material",
        alpha=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        sigma=[0.05] * 6,
    )
    assert "test_material" in db
    print(f"Registered test_material: {new_mat.alpha}")

    # 4. clamp check
    clamped = db.register(
        "clamped_mat",
        alpha=[0.0, 0.0, 1.5, 0.0, 0.0, 0.0],
        sigma=[0.05] * 6,
    )
    assert clamped.alpha[2] == 1.0, "Alpha should be clamped to 1.0"
    print(f"Clamped alpha[2]: {clamped.alpha[2]}")

    # 5. assign_materials
    surface_ids = ["floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"]
    assignments = {s: "concrete" for s in surface_ids}
    assignments["floor"] = "carpet"
    assignments["ceiling"] = "nonexistent_material"
    mat_map = assign_materials(surface_ids, assignments, db)
    assert mat_map["ceiling"].name == "default"
    print(f"Assigned materials: { {k: v.name for k, v in mat_map.items()} }")

    # 6. stochastic_material_variation
    var1 = stochastic_material_variation(concrete, variation_sigma=0.05, seed=42)
    var2 = stochastic_material_variation(concrete, variation_sigma=0.05, seed=42)
    assert np.allclose(var1.alpha, var2.alpha), "Same seed should produce identical output"
    print(f"Varied alpha: {var1.alpha}")

    # 7. export
    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "materials.json")
        exported = export_material_map(mat_map, out)
        print(f"Exported keys: {list(exported.keys())}")
        assert Path(out).exists()

    print("All smoke tests passed.")
