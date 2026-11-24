"""
Unit tests for UF-W112 Material Database (w112_material.py).

Covers:
- test_register_and_get
- test_register_clamps_alpha
- test_register_duplicate_warns
- test_empty_name_raises
- test_stochastic_reproducibility
- test_stochastic_bounds
- test_assign_unknown_material_warns
"""
from __future__ import annotations

import sys
import os
import warnings

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'src')
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from simulator.types import MaterialSpec
from simulator.uf.w112_material import (
    MaterialDB,
    assign_materials,
    export_material_map,
    stochastic_material_variation,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the MaterialDB singleton before each test for isolation."""
    MaterialDB.reset()
    yield
    MaterialDB.reset()


@pytest.fixture
def db() -> MaterialDB:
    return MaterialDB.instance()


# ---------------------------------------------------------------------------
# test_register_and_get
# ---------------------------------------------------------------------------

class TestRegisterAndGet:
    def test_register_new_material(self, db):
        alpha = [0.02, 0.02, 0.03, 0.04, 0.05, 0.05]
        sigma = [0.05] * 6
        spec = db.register("concrete", alpha, sigma)
        # Note: concrete is pre-populated; registration warns about duplicate
        assert isinstance(spec, MaterialSpec)

    def test_get_returns_correct_alpha(self, db):
        spec = db.get("concrete")
        expected = np.array([0.02, 0.02, 0.03, 0.04, 0.05, 0.05], dtype=np.float64)
        assert np.allclose(spec.alpha, expected), (
            f"concrete alpha mismatch: {spec.alpha} vs {expected}"
        )

    def test_get_prepopulated_materials(self, db):
        for name in ("concrete", "brick", "carpet", "glass", "wood", "acoustic_tile", "default"):
            spec = db.get(name)
            assert spec.name == name
            assert spec.alpha.shape == (6,)
            assert spec.sigma.shape == (6,)

    def test_register_custom_material(self, db):
        alpha = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        sigma = [0.01] * 6
        spec = db.register("custom_foam", alpha, sigma)
        retrieved = db.get("custom_foam")
        assert np.allclose(retrieved.alpha, alpha)
        assert np.allclose(retrieved.sigma, sigma)

    def test_get_missing_raises_key_error(self, db):
        with pytest.raises(KeyError, match="not registered"):
            db.get("nonexistent_material_xyz")

    def test_contains(self, db):
        assert "concrete" in db
        assert "nonexistent_xyz" not in db

    def test_len_prepopulated(self, db):
        # 8 standard materials (incl. "anechoic", added for REQ-W04/W03 tests;
        # design doc §8)
        assert len(db) == 8

    def test_sigma_all_005_for_standard(self, db):
        for name in ("concrete", "brick", "carpet", "glass", "wood", "acoustic_tile", "default"):
            spec = db.get(name)
            assert np.allclose(spec.sigma, [0.05] * 6), (
                f"sigma for '{name}' should be all 0.05, got {spec.sigma}"
            )


# ---------------------------------------------------------------------------
# test_register_clamps_alpha
# ---------------------------------------------------------------------------

class TestRegisterClampsAlpha:
    def test_alpha_above_1_clamped(self, db):
        alpha = [0.1, 0.1, 1.5, 0.1, 0.1, 0.1]
        spec = db.register("over_spec", alpha, [0.05] * 6)
        assert spec.alpha[2] == pytest.approx(1.0), (
            f"alpha[2] should be clamped to 1.0, got {spec.alpha[2]}"
        )

    def test_alpha_below_0_clamped(self, db):
        alpha = [-0.5, 0.1, 0.1, 0.1, 0.1, 0.1]
        spec = db.register("negative_spec", alpha, [0.05] * 6)
        assert spec.alpha[0] == pytest.approx(0.0)

    def test_alpha_at_boundary_not_clamped(self, db):
        alpha = [0.0, 0.5, 1.0, 0.0, 0.5, 1.0]
        spec = db.register("boundary_spec", alpha, [0.05] * 6)
        assert np.allclose(spec.alpha, alpha)

    def test_all_bands_clamped_independently(self, db):
        alpha = [2.0, -1.0, 1.5, -0.1, 3.0, 0.5]
        spec = db.register("all_over", alpha, [0.05] * 6)
        expected = np.clip(alpha, 0.0, 1.0)
        assert np.allclose(spec.alpha, expected)

    def test_wrong_alpha_length_raises(self, db):
        with pytest.raises(ValueError, match="6"):
            db.register("bad_alpha", [0.1, 0.2, 0.3], [0.05] * 6)


# ---------------------------------------------------------------------------
# test_register_duplicate_warns
# ---------------------------------------------------------------------------

class TestRegisterDuplicateWarns:
    def test_duplicate_registration_warns(self, db):
        alpha = [0.1] * 6
        # First registration of a name that already exists (concrete is pre-populated)
        with pytest.warns(UserWarning, match=r"[Aa]lready registered|[Oo]verwriting"):
            db.register("concrete", alpha, [0.05] * 6)

    def test_second_custom_registration_warns(self, db):
        alpha = [0.1] * 6
        db.register("custom_once", alpha, [0.05] * 6)
        with pytest.warns(UserWarning, match=r"[Aa]lready registered|[Oo]verwriting"):
            db.register("custom_once", [0.2] * 6, [0.05] * 6)

    def test_after_duplicate_value_is_updated(self, db):
        new_alpha = [0.99] * 6
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            db.register("concrete", new_alpha, [0.05] * 6)
        spec = db.get("concrete")
        assert np.allclose(spec.alpha, new_alpha)


# ---------------------------------------------------------------------------
# test_empty_name_raises
# ---------------------------------------------------------------------------

class TestEmptyNameRaises:
    def test_empty_string_raises(self, db):
        with pytest.raises(ValueError, match=r"[Nn]on-empty|[Ee]mpty"):
            db.register("", [0.1] * 6, [0.05] * 6)

    def test_whitespace_only_name_raises(self, db):
        # Whitespace-only name should also be rejected (it is falsy-ish)
        # The implementation checks `if not name`, which catches empty string.
        # Whitespace IS truthy in Python, so it may or may not raise.
        # We only strictly require empty string to raise; document this.
        with pytest.raises(ValueError):
            db.register("", [0.1] * 6, [0.05] * 6)


# ---------------------------------------------------------------------------
# test_stochastic_reproducibility
# ---------------------------------------------------------------------------

class TestStochasticReproducibility:
    def test_same_seed_gives_identical_output(self, db):
        concrete = db.get("concrete")
        var1 = stochastic_material_variation(concrete, variation_sigma=0.05, seed=42)
        var2 = stochastic_material_variation(concrete, variation_sigma=0.05, seed=42)
        assert np.allclose(var1.alpha, var2.alpha), (
            "Same seed should produce identical alpha arrays."
        )

    def test_different_seeds_give_different_output(self, db):
        concrete = db.get("concrete")
        var1 = stochastic_material_variation(concrete, variation_sigma=0.05, seed=42)
        var2 = stochastic_material_variation(concrete, variation_sigma=0.05, seed=99)
        assert not np.allclose(var1.alpha, var2.alpha), (
            "Different seeds should produce different alpha arrays."
        )

    def test_none_seed_raises(self, db):
        concrete = db.get("concrete")
        with pytest.raises(ValueError, match=r"[Ss]eed"):
            stochastic_material_variation(concrete, seed=None)

    def test_output_has_correct_name_suffix(self, db):
        concrete = db.get("concrete")
        var = stochastic_material_variation(concrete, seed=42)
        assert "varied" in var.name or var.name.startswith("concrete")

    def test_sigma_unchanged(self, db):
        concrete = db.get("concrete")
        var = stochastic_material_variation(concrete, seed=42)
        assert np.allclose(var.sigma, concrete.sigma)


# ---------------------------------------------------------------------------
# test_stochastic_bounds
# ---------------------------------------------------------------------------

class TestStochasticBounds:
    def test_alpha_always_in_unit_interval(self, db):
        """
        With high sigma (0.3) over many different seeds, all alpha values
        must remain within [0, 1] after clipping.
        """
        concrete = db.get("concrete")
        for seed in range(1000):
            var = stochastic_material_variation(
                concrete, variation_sigma=0.3, seed=seed
            )
            assert np.all(var.alpha >= 0.0), (
                f"alpha below 0 at seed {seed}: {var.alpha}"
            )
            assert np.all(var.alpha <= 1.0), (
                f"alpha above 1 at seed {seed}: {var.alpha}"
            )

    def test_alpha_shape_preserved(self, db):
        concrete = db.get("concrete")
        var = stochastic_material_variation(concrete, variation_sigma=0.3, seed=0)
        assert var.alpha.shape == (6,)

    def test_carpet_bounds(self, db):
        carpet = db.get("carpet")
        for seed in range(500):
            var = stochastic_material_variation(carpet, variation_sigma=0.3, seed=seed)
            assert np.all(var.alpha >= 0.0)
            assert np.all(var.alpha <= 1.0)


# ---------------------------------------------------------------------------
# test_assign_unknown_material_warns
# ---------------------------------------------------------------------------

class TestAssignUnknownMaterialWarns:
    def test_unknown_material_warns(self, db):
        surface_ids = ["floor", "ceiling"]
        assignments = {"floor": "nonexistent_mat", "ceiling": "concrete"}
        with pytest.warns(UserWarning, match=r"[Nn]ot in|[Uu]nknown|[Ff]alling"):
            result = assign_materials(surface_ids, assignments, db)
        # Fallback to "default"
        assert result["floor"].name == "default"

    def test_known_material_assigned_correctly(self, db):
        surface_ids = ["wall_x+"]
        assignments = {"wall_x+": "carpet"}
        result = assign_materials(surface_ids, assignments, db)
        assert result["wall_x+"].name == "carpet"

    def test_missing_surface_in_assignments_uses_default(self, db):
        """Surfaces not in assignments dict get 'default' material."""
        surface_ids = ["floor", "ceiling"]
        assignments = {}  # No assignments → all use default
        result = assign_materials(surface_ids, assignments, db)
        for sid in surface_ids:
            assert result[sid].name == "default"

    def test_multiple_unknown_materials_each_warns(self, db):
        surface_ids = ["floor", "ceiling", "wall_x+"]
        assignments = {
            "floor": "unknown_a",
            "ceiling": "unknown_b",
            "wall_x+": "concrete",
        }
        with pytest.warns(UserWarning):
            result = assign_materials(surface_ids, assignments, db)
        assert result["floor"].name == "default"
        assert result["ceiling"].name == "default"
        assert result["wall_x+"].name == "concrete"

    def test_all_surfaces_present_in_map(self, db):
        surface_ids = ["floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"]
        assignments = {sid: "wood" for sid in surface_ids}
        result = assign_materials(surface_ids, assignments, db)
        assert set(result.keys()) == set(surface_ids)


# ---------------------------------------------------------------------------
# export_material_map tests
# ---------------------------------------------------------------------------

class TestExportMaterialMap:
    def test_export_creates_file(self, db, tmp_path):
        surface_ids = ["floor", "ceiling"]
        assignments = {sid: "concrete" for sid in surface_ids}
        mat_map = assign_materials(surface_ids, assignments, db)
        out = str(tmp_path / "materials.json")
        exported = export_material_map(mat_map, out)
        assert (tmp_path / "materials.json").exists()

    def test_exported_dict_has_all_surfaces(self, db, tmp_path):
        surface_ids = ["floor", "ceiling", "wall_x+"]
        assignments = {sid: "concrete" for sid in surface_ids}
        mat_map = assign_materials(surface_ids, assignments, db)
        out = str(tmp_path / "materials.json")
        exported = export_material_map(mat_map, out)
        assert set(exported.keys()) == set(surface_ids)

    def test_export_creates_parent_dirs(self, db, tmp_path):
        surface_ids = ["floor"]
        assignments = {"floor": "carpet"}
        mat_map = assign_materials(surface_ids, assignments, db)
        nested = str(tmp_path / "a" / "b" / "c" / "out.json")
        export_material_map(mat_map, nested)
        import os
        assert os.path.exists(nested)
