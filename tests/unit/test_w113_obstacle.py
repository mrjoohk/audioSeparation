"""
Unit tests for UF-W113 Obstacle Placement (w113_obstacle.py).

Covers:
- test_placement_inside_room
- test_no_collision_after_placement
- test_role_tagging
- test_serialize_empty_layout
"""
from __future__ import annotations

import json
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

from simulator.types import AABB, ObjectSpec, PlacedObject
from simulator.uf.w113_obstacle import (
    check_collisions,
    place_obstacle_objects,
    serialize_obstacle_layout,
    tag_acoustic_roles,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def room_bbox() -> AABB:
    return AABB(
        min_corner=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        max_corner=np.array([10.0, 3.0, 8.0], dtype=np.float64),
    )


@pytest.fixture
def basic_specs() -> list[ObjectSpec]:
    return [
        ObjectSpec(object_type="chair",     size=np.array([0.5, 0.9, 0.5])),
        ObjectSpec(object_type="table",     size=np.array([1.2, 0.75, 0.8])),
        ObjectSpec(object_type="partition", size=np.array([0.1, 2.0, 1.5])),
    ]


# ---------------------------------------------------------------------------
# test_placement_inside_room
# ---------------------------------------------------------------------------

class TestPlacementInsideRoom:
    def test_all_positions_inside_bbox(self, room_bbox, basic_specs):
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        assert len(layout) == len(basic_specs), (
            f"Expected {len(basic_specs)} objects placed, got {len(layout)}"
        )
        for obj in layout:
            # Object AABB must be fully inside room_bbox
            aabb = obj.aabb
            assert np.all(aabb.min_corner >= room_bbox.min_corner), (
                f"Object '{obj.object_id}' min_corner {aabb.min_corner} is outside room."
            )
            assert np.all(aabb.max_corner <= room_bbox.max_corner), (
                f"Object '{obj.object_id}' max_corner {aabb.max_corner} is outside room."
            )

    def test_positions_respect_wall_clearance(self, room_bbox, basic_specs):
        """Object AABB should be at least 0.3 m from each wall."""
        clearance = 0.3
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        for obj in layout:
            aabb = obj.aabb
            for dim in range(3):
                assert aabb.min_corner[dim] >= room_bbox.min_corner[dim] + clearance - 1e-9, (
                    f"Object '{obj.object_id}' too close to low wall in dim {dim}."
                )
                assert aabb.max_corner[dim] <= room_bbox.max_corner[dim] - clearance + 1e-9, (
                    f"Object '{obj.object_id}' too close to high wall in dim {dim}."
                )

    def test_result_is_list_of_placed_objects(self, room_bbox, basic_specs):
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=42)
        assert isinstance(layout, list)
        for obj in layout:
            assert isinstance(obj, PlacedObject)

    def test_different_seeds_give_different_positions(self, room_bbox, basic_specs):
        layout_a = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        layout_b = place_obstacle_objects(room_bbox, basic_specs, seed=1)
        # At least one object position should differ
        any_different = any(
            not np.allclose(a.position, b.position)
            for a, b in zip(layout_a, layout_b)
        )
        assert any_different, "Different seeds should produce different layouts."

    def test_same_seed_reproducible(self, room_bbox, basic_specs):
        layout_a = place_obstacle_objects(room_bbox, basic_specs, seed=77)
        layout_b = place_obstacle_objects(room_bbox, basic_specs, seed=77)
        for a, b in zip(layout_a, layout_b):
            assert np.allclose(a.position, b.position)

    def test_empty_specs_returns_empty_layout(self, room_bbox):
        layout = place_obstacle_objects(room_bbox, [], seed=0)
        assert layout == []

    def test_too_large_object_warns(self):
        """Object larger than room causes a warning and is skipped."""
        tiny_bbox = AABB(
            min_corner=np.array([0.0, 0.0, 0.0]),
            max_corner=np.array([1.0, 1.0, 1.0]),
        )
        huge_spec = [ObjectSpec(object_type="table", size=np.array([5.0, 5.0, 5.0]))]
        with pytest.warns(UserWarning, match=r"[Cc]annot fit|[Ss]kipping|[Ss]mall"):
            layout = place_obstacle_objects(tiny_bbox, huge_spec, seed=0)
        assert layout == []

    def test_rotation_y_in_valid_range(self, room_bbox, basic_specs):
        """rotation_y must be in [0, 2π)."""
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        for obj in layout:
            assert 0.0 <= obj.rotation_y < 2 * np.pi + 1e-9


# ---------------------------------------------------------------------------
# test_no_collision_after_placement
# ---------------------------------------------------------------------------

class TestNoCollisionAfterPlacement:
    def test_collision_check_passes(self, room_bbox, basic_specs):
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        result = check_collisions(layout, room_bbox)
        assert result["n_violations"] == 0, (
            f"Expected 0 violations after placement, got {result['n_violations']}: "
            f"{result['violating_pairs']}"
        )

    def test_collision_result_has_required_keys(self, room_bbox, basic_specs):
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        result = check_collisions(layout, room_bbox)
        assert "n_violations" in result
        assert "violating_pairs" in result

    def test_forced_overlap_detected(self, room_bbox):
        """Manually place two objects at the same position → collision."""
        pos = np.array([5.0, 1.5, 4.0], dtype=np.float64)
        size = np.array([1.0, 1.0, 1.0], dtype=np.float64)
        obj_a = PlacedObject(
            object_id="obj_a", object_type="table",
            position=pos.copy(), size=size.copy(),
            rotation_y=0.0, acoustic_role="reflective"
        )
        obj_b = PlacedObject(
            object_id="obj_b", object_type="table",
            position=pos.copy(), size=size.copy(),
            rotation_y=0.0, acoustic_role="reflective"
        )
        result = check_collisions([obj_a, obj_b], room_bbox)
        assert result["n_violations"] > 0

    def test_empty_layout_no_violations(self, room_bbox):
        result = check_collisions([], room_bbox)
        assert result["n_violations"] == 0
        assert result["violating_pairs"] == []

    def test_single_object_no_collision_with_itself(self, room_bbox):
        pos = np.array([5.0, 1.0, 4.0], dtype=np.float64)
        size = np.array([0.5, 0.5, 0.5], dtype=np.float64)
        obj = PlacedObject(
            object_id="solo", object_type="chair",
            position=pos, size=size,
            rotation_y=0.0, acoustic_role="absorptive"
        )
        result = check_collisions([obj], room_bbox)
        assert result["n_violations"] == 0


# ---------------------------------------------------------------------------
# test_role_tagging
# ---------------------------------------------------------------------------

class TestRoleTagging:
    def test_partition_tagged_as_occluding(self, room_bbox):
        spec = [ObjectSpec(object_type="partition", size=np.array([0.1, 2.0, 1.5]))]
        layout = place_obstacle_objects(room_bbox, spec, seed=0)
        tagged = tag_acoustic_roles(layout)
        assert tagged[0].acoustic_role == "occluding"

    def test_chair_tagged_as_absorptive(self, room_bbox):
        spec = [ObjectSpec(object_type="chair", size=np.array([0.5, 0.9, 0.5]))]
        layout = place_obstacle_objects(room_bbox, spec, seed=0)
        tagged = tag_acoustic_roles(layout)
        assert tagged[0].acoustic_role == "absorptive"

    def test_table_tagged_as_reflective(self, room_bbox):
        spec = [ObjectSpec(object_type="table", size=np.array([1.2, 0.75, 0.8]))]
        layout = place_obstacle_objects(room_bbox, spec, seed=0)
        tagged = tag_acoustic_roles(layout)
        assert tagged[0].acoustic_role == "reflective"

    def test_unknown_type_tagged_as_reflective_with_warning(self, room_bbox):
        pos = np.array([5.0, 1.0, 4.0], dtype=np.float64)
        size = np.array([0.5, 0.5, 0.5], dtype=np.float64)
        obj = PlacedObject(
            object_id="unknown_0", object_type="spaceship",
            position=pos, size=size,
            rotation_y=0.0, acoustic_role="reflective"
        )
        with pytest.warns(UserWarning, match=r"[Nn]o role|[Uu]nknown|reflective"):
            tagged = tag_acoustic_roles([obj])
        assert tagged[0].acoustic_role == "reflective"

    def test_custom_role_map_applied(self, room_bbox):
        spec = [ObjectSpec(object_type="pillar", size=np.array([0.3, 2.5, 0.3]))]
        layout = place_obstacle_objects(room_bbox, spec, seed=0)
        custom_map = {"pillar": "occluding"}
        tagged = tag_acoustic_roles(layout, role_map=custom_map)
        assert tagged[0].acoustic_role == "occluding"

    def test_original_layout_not_mutated(self, room_bbox):
        spec = [ObjectSpec(object_type="chair", size=np.array([0.5, 0.9, 0.5]))]
        layout = place_obstacle_objects(room_bbox, spec, seed=0)
        original_role = layout[0].acoustic_role
        tag_acoustic_roles(layout, role_map={"chair": "occluding"})
        assert layout[0].acoustic_role == original_role, (
            "tag_acoustic_roles should not mutate the original layout."
        )


# ---------------------------------------------------------------------------
# test_serialize_empty_layout
# ---------------------------------------------------------------------------

class TestSerializeEmptyLayout:
    def test_empty_layout_writes_empty_list(self, tmp_path):
        out = str(tmp_path / "layout.json")
        exported = serialize_obstacle_layout([], out)
        with open(out, "r") as fh:
            data = json.load(fh)
        assert data == [], f"Expected empty list in JSON, got: {data}"

    def test_serialize_creates_file(self, tmp_path, room_bbox, basic_specs):
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        out = str(tmp_path / "layout.json")
        serialize_obstacle_layout(layout, out)
        assert os.path.exists(out)

    def test_serialize_roundtrip_fields(self, tmp_path, room_bbox, basic_specs):
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        out = str(tmp_path / "layout.json")
        exported = serialize_obstacle_layout(layout, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        for item in loaded:
            assert "object_id" in item
            assert "object_type" in item
            assert "position" in item
            assert "size" in item
            assert "rotation_y" in item
            assert "acoustic_role" in item

    def test_serialize_creates_parent_dirs(self, tmp_path):
        out = str(tmp_path / "deep" / "nested" / "layout.json")
        serialize_obstacle_layout([], out)
        assert os.path.exists(out)

    def test_serialized_positions_are_lists(self, tmp_path, room_bbox, basic_specs):
        layout = place_obstacle_objects(room_bbox, basic_specs, seed=0)
        out = str(tmp_path / "layout.json")
        serialize_obstacle_layout(layout, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        for item in loaded:
            assert isinstance(item["position"], list)
            assert len(item["position"]) == 3
