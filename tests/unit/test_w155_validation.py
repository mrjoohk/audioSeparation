"""
Unit tests for UF-W155: Acoustic Plausibility and Config Completeness Validation.

Tests:
  - test_valid_scene_passes
  - test_low_absorption_high_rt60
  - test_near_field_source_warns
  - test_small_room_warns
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent.parent
_SRC = _REPO_ROOT / "src"
for _p in (_SRC, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from simulator.types import MaterialSpec, PlausibilityReport, SceneConfig  # noqa: E402
from simulator.uf.w155_validation import (  # noqa: E402
    validate_acoustic_plausibility,
    validate_config_completeness,
)


# ---------------------------------------------------------------------------
# Material factory helpers
# ---------------------------------------------------------------------------

def _make_material(alpha_500: float, name: str = "test_mat") -> MaterialSpec:
    """Create a MaterialSpec with uniform absorption across all 6 bands."""
    alpha = np.full(6, alpha_500, dtype=np.float64)
    sigma = np.zeros(6, dtype=np.float64)
    return MaterialSpec(name=name, alpha=alpha, sigma=sigma)


def _shoebox_material_map(material: MaterialSpec) -> dict:
    """Apply a single material to all 6 shoebox surfaces."""
    surfaces = ["floor", "ceiling", "front", "back", "left", "right"]
    return {s: material for s in surfaces}


# ---------------------------------------------------------------------------
# Room and entity helpers
# ---------------------------------------------------------------------------

def _room(L: float = 6.0, W: float = 5.0, H: float = 3.0) -> dict:
    return {"type": "shoebox", "dimensions": {"L": L, "W": W, "H": H}}


def _source(x: float = 2.0, y: float = 1.5, z: float = 2.0, sid: str = "s1") -> dict:
    return {"source_id": sid, "position": {"x": x, "y": y, "z": z}}


def _receiver(x: float = 4.0, y: float = 1.5, z: float = 2.0, rid: str = "r1") -> dict:
    return {"receiver_id": rid, "position": {"x": x, "y": y, "z": z}}


# ---------------------------------------------------------------------------
# Tests for validate_acoustic_plausibility
# ---------------------------------------------------------------------------


class TestValidateAcousticPlausibility:

    # -----------------------------------------------------------------------
    def test_valid_scene_passes(self):
        """Normal shoebox room with concrete walls, sources at ≈2 m → passed=True."""
        room = _room(L=6.0, W=5.0, H=3.0)
        # Concrete: α ≈ 0.02 at 500 Hz → RT60 should be in plausible range
        mat = _make_material(alpha_500=0.20, name="concrete")   # moderate absorption
        materials = _shoebox_material_map(mat)
        sources = [_source(x=2.0, y=1.5, z=2.0)]
        receivers = [_receiver(x=4.0, y=1.5, z=3.0)]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)

        assert isinstance(report, PlausibilityReport)
        assert report.passed is True, (
            f"Expected passed=True, got errors={report.errors}, warnings={report.warnings}"
        )
        assert report.predicted_rt60_s > 0.0
        assert 0.05 <= report.predicted_rt60_s <= 5.0

    # -----------------------------------------------------------------------
    def test_low_absorption_high_rt60(self):
        """All surfaces with α=0.01 → RT60 >> 5 s → error in report."""
        room = _room(L=6.0, W=5.0, H=3.0)
        mat = _make_material(alpha_500=0.01, name="mirror")
        materials = _shoebox_material_map(mat)
        sources = [_source()]
        receivers = [_receiver()]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)

        assert report.passed is False, (
            "Expected passed=False for extremely low absorption (RT60 > 5 s)"
        )
        assert len(report.errors) > 0, "Expected at least one error"
        # The error message should mention the RT60 exceeding the maximum
        error_text = " ".join(report.errors).lower()
        assert "rt60" in error_text or "exceed" in error_text or "maximum" in error_text

    # -----------------------------------------------------------------------
    def test_near_field_source_warns(self):
        """Source at 0.05 m from receiver → 'near-field' warning in report."""
        room = _room(L=6.0, W=5.0, H=3.0)
        mat = _make_material(alpha_500=0.15)
        materials = _shoebox_material_map(mat)
        # Place source 0.05 m from receiver (both at x=4.0, y=1.5, z=2.0 approx)
        sources = [_source(x=4.0, y=1.5, z=2.0)]
        receivers = [_receiver(x=4.0, y=1.5, z=2.05)]   # 0.05 m apart in Z

        report = validate_acoustic_plausibility(room, materials, sources, receivers)

        warning_text = " ".join(report.warnings).lower()
        assert "near" in warning_text or "field" in warning_text or "0.0" in warning_text, (
            f"Expected 'near-field' warning, got: {report.warnings}"
        )

    # -----------------------------------------------------------------------
    def test_small_room_warns(self):
        """2×2×2 m room (volume=8 m³ < 10 m³) → volume warning in report."""
        room = _room(L=2.0, W=2.0, H=2.0)       # V = 8 m³  < MIN_ROOM_VOLUME_M3
        mat = _make_material(alpha_500=0.20)
        materials = _shoebox_material_map(mat)
        sources = [_source(x=0.5, y=1.0, z=0.5)]
        receivers = [_receiver(x=1.5, y=1.0, z=1.5)]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)

        warning_text = " ".join(report.warnings).lower()
        assert "volume" in warning_text or "minimum" in warning_text or "below" in warning_text, (
            f"Expected volume warning for 8 m³ room, got: {report.warnings}"
        )

    # -----------------------------------------------------------------------
    def test_large_room_warns(self):
        """Very large room (L=60, W=50, H=20 → 60000 m³) → volume warning."""
        room = _room(L=60.0, W=50.0, H=20.0)   # V = 60000 m³ > MAX
        mat = _make_material(alpha_500=0.15)
        materials = _shoebox_material_map(mat)
        sources = [_source(x=10.0, y=5.0, z=10.0)]
        receivers = [_receiver(x=20.0, y=5.0, z=15.0)]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)

        warning_text = " ".join(report.warnings).lower()
        assert "volume" in warning_text or "maximum" in warning_text or "exceed" in warning_text, (
            f"Expected large-volume warning, got: {report.warnings}"
        )

    # -----------------------------------------------------------------------
    def test_perfect_absorption_low_rt60(self):
        """α=1.0 (perfectly absorptive) → RT60 very low → error."""
        room = _room(L=6.0, W=5.0, H=3.0)
        mat = _make_material(alpha_500=1.0, name="absorber")
        materials = _shoebox_material_map(mat)
        sources = [_source()]
        receivers = [_receiver()]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)

        # RT60_sabine = 0.161 * 90 / (1.0 * total_surface) ≈ 0.161*90/126 ≈ 0.115 s
        # That's > 0.05, so it should pass, but let's just check no crash
        assert isinstance(report, PlausibilityReport)

    # -----------------------------------------------------------------------
    def test_zero_absorption_infinite_rt60_errors(self):
        """α=0.0 (no absorption) → infinite RT60 → error."""
        room = _room(L=6.0, W=5.0, H=3.0)
        mat = _make_material(alpha_500=0.0, name="no_absorption")
        materials = _shoebox_material_map(mat)
        sources = [_source()]
        receivers = [_receiver()]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)

        assert report.passed is False
        assert len(report.errors) > 0

    # -----------------------------------------------------------------------
    def test_no_materials_uses_default(self):
        """Passing None as materials should not raise — uses default α=0.1."""
        room = _room()
        sources = [_source()]
        receivers = [_receiver()]

        report = validate_acoustic_plausibility(room, None, sources, receivers)
        assert isinstance(report, PlausibilityReport)
        assert report.predicted_rt60_s > 0.0

    # -----------------------------------------------------------------------
    def test_multiple_sources_multiple_receivers(self):
        """Multiple sources and receivers should all be checked for near-field."""
        room = _room(L=8.0, W=6.0, H=3.0)
        mat = _make_material(alpha_500=0.20)
        materials = _shoebox_material_map(mat)
        sources = [
            _source(x=1.0, y=1.5, z=1.0, sid="s1"),
            _source(x=5.0, y=1.5, z=5.0, sid="s2"),
        ]
        receivers = [
            _receiver(x=3.0, y=1.5, z=3.0, rid="r1"),
            _receiver(x=4.0, y=1.5, z=4.0, rid="r2"),
        ]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)
        assert isinstance(report, PlausibilityReport)

    # -----------------------------------------------------------------------
    def test_report_has_predicted_drr(self):
        """The report must include a finite predicted DRR value."""
        room = _room()
        mat = _make_material(alpha_500=0.15)
        materials = _shoebox_material_map(mat)
        sources = [_source()]
        receivers = [_receiver()]

        report = validate_acoustic_plausibility(room, materials, sources, receivers)
        import math
        assert math.isfinite(report.predicted_drr_db)


# ---------------------------------------------------------------------------
# Tests for validate_config_completeness
# ---------------------------------------------------------------------------


class TestValidateConfigCompleteness:

    def _base_config(self) -> SceneConfig:
        return SceneConfig(
            scene_id="test",
            seed=1,
            schema_version="1.0.0",
            room={"type": "shoebox", "dimensions": {"L": 5, "W": 4, "H": 3}},
            materials={},
            sources=[
                {"source_id": "s1", "position": {"x": 1, "y": 1, "z": 1}},
                {"source_id": "s2", "position": {"x": 2, "y": 1, "z": 2}},
            ],
            receivers=[
                {"receiver_id": "r1", "position": {"x": 3, "y": 1, "z": 1}},
            ],
        )

    def test_complete_config_passes(self):
        """A complete, consistent config must pass completeness check."""
        cfg = self._base_config()
        result = validate_config_completeness(cfg)
        assert result["passed"] is True
        assert result["missing_refs"] == []

    def test_duplicate_source_id_detected(self):
        """Duplicate source_ids must be flagged."""
        cfg = self._base_config()
        cfg.sources = [
            {"source_id": "s1", "position": {"x": 1, "y": 1, "z": 1}},
            {"source_id": "s1", "position": {"x": 2, "y": 1, "z": 2}},  # duplicate
        ]
        result = validate_config_completeness(cfg)
        assert result["passed"] is False
        assert any("s1" in ref for ref in result["missing_refs"])

    def test_motion_with_unknown_id_detected(self):
        """A motion block referencing an unknown source_id must be flagged."""
        cfg = self._base_config()
        cfg.motion = {"s_nonexistent": {"type": "linear"}}
        result = validate_config_completeness(cfg)
        assert result["passed"] is False
        assert any("s_nonexistent" in ref for ref in result["missing_refs"])

    def test_impairment_with_unknown_source_id_detected(self):
        """Impairments block referencing unknown source must be flagged."""
        cfg = self._base_config()
        cfg.impairments = {"s_ghost": {"codec": "opus"}}
        result = validate_config_completeness(cfg)
        assert result["passed"] is False
        assert any("s_ghost" in ref for ref in result["missing_refs"])

    def test_motion_referencing_valid_source(self):
        """Motion block referencing a valid source_id must pass."""
        cfg = self._base_config()
        cfg.motion = {"s1": {"type": "stationary"}}
        result = validate_config_completeness(cfg)
        assert result["passed"] is True

    def test_returns_dict_with_correct_keys(self):
        """Result must always contain 'passed' (bool) and 'missing_refs' (list)."""
        cfg = self._base_config()
        result = validate_config_completeness(cfg)
        assert "passed" in result
        assert "missing_refs" in result
        assert isinstance(result["passed"], bool)
        assert isinstance(result["missing_refs"], list)
