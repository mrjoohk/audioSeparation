"""
Unit tests for UF-W114 Coordinate Transforms (w114_transforms.py).

Coordinate convention used throughout: row-vector right-multiply.
    world_pos_h = [x, y, z, 1] @ T

Translation is therefore stored in T[3, :3] (the last row).
make_translation_matrix(tx, ty, tz) builds such a matrix.

Covers:
- test_identity_transform
- test_local_to_world_translation
- test_tick_lookup_clamp
- test_consistency_teleportation
"""
from __future__ import annotations

import sys
import os

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

from simulator.types import WorldFrame
from simulator.uf.w114_transforms import (
    TransformError,
    define_world_frame,
    get_transform_at_tick,
    local_to_world,
    make_translation_matrix,
    validate_transform_consistency,
)


# ---------------------------------------------------------------------------
# test_identity_transform
# ---------------------------------------------------------------------------

class TestIdentityTransform:
    @pytest.mark.parametrize("pos", [
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 3.0],
        [-5.0, 0.5, 10.0],
    ])
    def test_identity_preserves_position(self, pos):
        identity = np.eye(4, dtype=np.float64)
        local = np.array(pos, dtype=np.float64)
        result = local_to_world(local, identity)
        assert np.allclose(result, local), (
            f"Identity transform changed position: {result} != {local}"
        )

    def test_result_has_shape_3(self):
        result = local_to_world(np.array([1.0, 2.0, 3.0]), np.eye(4))
        assert result.shape == (3,)

    def test_result_is_float64(self):
        result = local_to_world(np.array([1.0, 2.0, 3.0]), np.eye(4))
        assert result.dtype == np.float64

    def test_degenerate_matrix_raises(self):
        degenerate = np.zeros((4, 4), dtype=np.float64)
        with pytest.raises(TransformError, match=r"[Dd]egenerate|[Dd]et"):
            local_to_world(np.array([1.0, 0.0, 0.0]), degenerate)

    def test_wrong_transform_shape_raises(self):
        bad_T = np.eye(3, dtype=np.float64)
        with pytest.raises(TransformError):
            local_to_world(np.array([1.0, 0.0, 0.0]), bad_T)

    def test_uniform_scale_transform(self):
        """Uniform scale 2× should double the position components (no translation)."""
        scale = np.diag([2.0, 2.0, 2.0, 1.0]).astype(np.float64)
        pos = np.array([1.0, 1.0, 1.0])
        result = local_to_world(pos, scale)
        assert np.allclose(result, [2.0, 2.0, 2.0])


# ---------------------------------------------------------------------------
# test_local_to_world_translation
# ---------------------------------------------------------------------------

class TestLocalToWorldTranslation:
    def test_translation_shifts_origin(self):
        """
        Row-vector convention: [0,0,0,1] @ T = T[3,:], so T[3,:3] = [tx,ty,tz].
        make_translation_matrix builds exactly this.
        """
        T = make_translation_matrix(1.0, 2.0, 3.0)
        origin = np.array([0.0, 0.0, 0.0])
        result = local_to_world(origin, T)
        assert np.allclose(result, [1.0, 2.0, 3.0]), (
            f"Expected [1.0, 2.0, 3.0], got {result}"
        )

    def test_translation_adds_to_existing_position(self):
        """Non-zero local position is also shifted by the translation."""
        T = make_translation_matrix(10.0, 0.0, 0.0)
        pos = np.array([1.0, 0.0, 0.0])
        result = local_to_world(pos, T)
        assert np.allclose(result, [11.0, 0.0, 0.0])

    def test_negative_translation(self):
        T = make_translation_matrix(-5.0, -3.0, -1.0)
        pos = np.array([0.0, 0.0, 0.0])
        result = local_to_world(pos, T)
        assert np.allclose(result, [-5.0, -3.0, -1.0])

    def test_translation_in_all_three_axes(self):
        T = make_translation_matrix(1.0, 2.0, 3.0)
        pos = np.array([1.0, 1.0, 1.0])
        result = local_to_world(pos, T)
        assert np.allclose(result, [2.0, 3.0, 4.0])

    def test_make_translation_matrix_structure(self):
        """Verify the matrix layout: row 3 holds the translation."""
        T = make_translation_matrix(4.0, 5.0, 6.0)
        assert T.shape == (4, 4)
        assert T[3, 0] == pytest.approx(4.0)
        assert T[3, 1] == pytest.approx(5.0)
        assert T[3, 2] == pytest.approx(6.0)
        # Diagonal should be 1
        assert T[0, 0] == pytest.approx(1.0)
        assert T[1, 1] == pytest.approx(1.0)
        assert T[2, 2] == pytest.approx(1.0)
        assert T[3, 3] == pytest.approx(1.0)

    def test_zero_translation_is_identity(self):
        T = make_translation_matrix(0.0, 0.0, 0.0)
        assert np.allclose(T, np.eye(4))


# ---------------------------------------------------------------------------
# test_tick_lookup_clamp
# ---------------------------------------------------------------------------

class TestTickLookupClamp:
    @pytest.fixture
    def simple_sequence(self) -> dict:
        return {
            "entity_0": [
                make_translation_matrix(0.0, 0.0, 0.0),
                make_translation_matrix(1.0, 0.0, 0.0),
                make_translation_matrix(2.0, 0.0, 0.0),
            ]
        }

    def test_tick_0_returns_first(self, simple_sequence):
        T = get_transform_at_tick("entity_0", 0, simple_sequence)
        # Translation is in T[3, 0] (row-vector convention)
        assert T[3, 0] == pytest.approx(0.0)

    def test_tick_1_returns_second(self, simple_sequence):
        T = get_transform_at_tick("entity_0", 1, simple_sequence)
        assert T[3, 0] == pytest.approx(1.0)

    def test_tick_2_returns_third(self, simple_sequence):
        T = get_transform_at_tick("entity_0", 2, simple_sequence)
        assert T[3, 0] == pytest.approx(2.0)

    def test_tick_beyond_length_clamps_to_last(self, simple_sequence):
        T = get_transform_at_tick("entity_0", 999, simple_sequence)
        assert T[3, 0] == pytest.approx(2.0), (
            f"Clamped tick should return last element; T[3,0]={T[3,0]}"
        )

    def test_tick_exactly_at_last_valid(self, simple_sequence):
        T = get_transform_at_tick("entity_0", 2, simple_sequence)
        T_clamped = get_transform_at_tick("entity_0", 100, simple_sequence)
        assert np.allclose(T, T_clamped)

    def test_missing_entity_raises_key_error(self, simple_sequence):
        with pytest.raises(KeyError, match=r"entity|not found"):
            get_transform_at_tick("missing_entity", 0, simple_sequence)

    def test_single_tick_sequence_always_returns_it(self):
        seq = {"ent": [np.eye(4, dtype=np.float64)]}
        for tick_id in [0, 1, 100]:
            T = get_transform_at_tick("ent", tick_id, seq)
            assert np.allclose(T, np.eye(4))

    def test_returns_float64_array(self, simple_sequence):
        T = get_transform_at_tick("entity_0", 0, simple_sequence)
        assert T.dtype == np.float64
        assert T.shape == (4, 4)


# ---------------------------------------------------------------------------
# test_consistency_teleportation
# ---------------------------------------------------------------------------

class TestConsistencyTeleportation:
    def test_normal_motion_passes(self):
        """Small displacement within speed limit → no violation.

        0.01 m per tick at 50 Hz = 0.5 m/s < 2.0 m/s
        """
        T0 = make_translation_matrix(0.00, 0.0, 0.0)
        T1 = make_translation_matrix(0.01, 0.0, 0.0)
        T2 = make_translation_matrix(0.02, 0.0, 0.0)
        result = validate_transform_consistency(
            {"walker": [T0, T1, T2]},
            max_speed_m_per_s=2.0,
            tick_rate_hz=50.0,
        )
        assert result["passed"] is True
        assert result["violations"] == []

    def test_teleportation_detected(self):
        """Large jump in one tick → violation detected."""
        T0 = make_translation_matrix(0.0, 0.0, 0.0)
        T_jump = make_translation_matrix(100.0, 0.0, 0.0)  # 100 m in one tick
        result = validate_transform_consistency(
            {"teleporter": [T0, T_jump]},
            max_speed_m_per_s=2.0,
            tick_rate_hz=50.0,
        )
        assert result["passed"] is False
        assert len(result["violations"]) >= 1

    def test_violation_message_contains_entity_id(self):
        T0 = make_translation_matrix(0.0, 0.0, 0.0)
        T_jump = make_translation_matrix(50.0, 0.0, 0.0)
        result = validate_transform_consistency(
            {"fast_car": [T0, T_jump]},
        )
        assert any("fast_car" in v for v in result["violations"])

    def test_exactly_at_threshold_passes(self):
        """Displacement = max_speed / tick_rate (at the threshold boundary)."""
        max_speed = 2.0
        tick_rate = 50.0
        threshold = max_speed / tick_rate  # 0.04 m
        T0 = make_translation_matrix(0.0, 0.0, 0.0)
        T1 = make_translation_matrix(threshold, 0.0, 0.0)
        result = validate_transform_consistency(
            {"entity": [T0, T1]},
            max_speed_m_per_s=max_speed,
            tick_rate_hz=tick_rate,
        )
        assert result["passed"] is True

    def test_just_above_threshold_fails(self):
        max_speed = 2.0
        tick_rate = 50.0
        threshold = max_speed / tick_rate + 1e-4  # slightly above
        T0 = make_translation_matrix(0.0, 0.0, 0.0)
        T1 = make_translation_matrix(threshold, 0.0, 0.0)
        result = validate_transform_consistency(
            {"entity": [T0, T1]},
            max_speed_m_per_s=max_speed,
            tick_rate_hz=tick_rate,
        )
        assert result["passed"] is False

    def test_multiple_entities_independent(self):
        T0 = make_translation_matrix(0.0, 0.0, 0.0)
        T_ok = make_translation_matrix(0.01, 0.0, 0.0)
        T_bad = make_translation_matrix(50.0, 0.0, 0.0)
        result = validate_transform_consistency({
            "normal": [T0, T_ok],
            "teleporter": [T0, T_bad],
        })
        assert result["passed"] is False
        # Only teleporter should be in violations
        assert all("teleporter" in v for v in result["violations"])

    def test_empty_sequence_passes(self):
        result = validate_transform_consistency({})
        assert result["passed"] is True
        assert result["violations"] == []

    def test_single_tick_per_entity_passes(self):
        """Single-tick sequences cannot have transitions → no violations."""
        T0 = make_translation_matrix(100.0, 100.0, 100.0)
        result = validate_transform_consistency({"ent": [T0]})
        assert result["passed"] is True

    def test_result_has_required_keys(self):
        result = validate_transform_consistency({})
        assert "passed" in result
        assert "violations" in result

    def test_violations_is_list_of_strings(self):
        T0 = make_translation_matrix(0.0, 0.0, 0.0)
        T_bad = make_translation_matrix(99.0, 0.0, 0.0)
        result = validate_transform_consistency({"e": [T0, T_bad]})
        assert isinstance(result["violations"], list)
        for v in result["violations"]:
            assert isinstance(v, str)


# ---------------------------------------------------------------------------
# define_world_frame tests
# ---------------------------------------------------------------------------

class TestDefineWorldFrame:
    def test_default_origin_is_zeros(self):
        frame = define_world_frame()
        assert np.allclose(frame.origin, [0.0, 0.0, 0.0])

    def test_custom_origin(self):
        frame = define_world_frame(origin=[1.0, 2.0, 3.0])
        assert np.allclose(frame.origin, [1.0, 2.0, 3.0])

    def test_y_up_convention(self):
        frame = define_world_frame(convention="Y-up-RH")
        assert frame.convention == "Y-up-RH"

    def test_z_up_convention(self):
        frame = define_world_frame(convention="Z-up-RH")
        assert frame.convention == "Z-up-RH"

    def test_unsupported_convention_raises(self):
        with pytest.raises(ValueError, match=r"[Uu]nsupported|convention"):
            define_world_frame(convention="X-up")

    def test_unit_is_meters(self):
        frame = define_world_frame()
        assert frame.unit == "meters"

    def test_returns_world_frame_instance(self):
        frame = define_world_frame()
        assert isinstance(frame, WorldFrame)
