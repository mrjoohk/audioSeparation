"""
Unit tests for UF-W111 Room Geometry (w111_room_geometry.py).

Covers:
- test_shoebox_dimensions
- test_small_dimension_raises
- test_low_headroom_warns
- test_bounding_volume_shoebox
- test_manifold_valid
- test_manifold_invalid
"""
from __future__ import annotations

import sys
import os
import warnings

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup — allow running directly or via pytest from repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'src')
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from simulator.types import AABB, MeshRoom, MeshValidationResult, RoomPrimitive
from simulator.uf.w111_room_geometry import (
    MeshError,
    define_room_primitive,
    generate_bounding_volume,
    validate_manifold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tetrahedron() -> MeshRoom:
    """Build a valid closed tetrahedron MeshRoom."""
    verts = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.5, 1.0, 0.0],
        [0.5, 0.5, 1.0],
    ], dtype=np.float64)
    faces = np.array([
        [0, 2, 1],
        [0, 1, 3],
        [1, 2, 3],
        [0, 3, 2],
    ], dtype=np.int64)
    normals = _compute_normals(verts, faces)
    return MeshRoom(vertices=verts, faces=faces, surface_normals=normals)


def _compute_normals(verts, faces):
    normals = []
    for f in faces:
        v0, v1, v2 = verts[f[0]], verts[f[1]], verts[f[2]]
        n = np.cross(v1 - v0, v2 - v0)
        length = np.linalg.norm(n)
        normals.append(n / (length + 1e-12))
    return np.array(normals, dtype=np.float64)


# ---------------------------------------------------------------------------
# test_shoebox_dimensions
# ---------------------------------------------------------------------------

class TestShoeboxDimensions:
    def test_surface_count(self):
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        assert len(room.surfaces) == 6, "Shoebox must have exactly 6 surfaces."

    def test_volume(self):
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        assert abs(room.volume_m3 - 60.0) < 0.001, (
            f"Expected volume 60.0 m³, got {room.volume_m3:.6f} m³."
        )

    def test_surface_ids(self):
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        expected = {"floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"}
        assert set(room.surface_ids) == expected

    def test_room_type(self):
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        assert room.room_type == "shoebox"

    def test_corridor_type(self):
        room = define_room_primitive("corridor", {"L": 10.0, "W": 2.0, "H": 2.5})
        assert room.room_type == "corridor"
        assert len(room.surfaces) == 6

    def test_hall_with_arch_height(self):
        room = define_room_primitive(
            "hall", {"L": 15.0, "W": 8.0, "H": 5.0, "arch_height": 6.0}
        )
        assert room.room_type == "hall"
        assert "arch_height" in room.dimensions
        assert room.dimensions["arch_height"] == 6.0

    def test_normals_are_unit_vectors(self):
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        for surface in room.surfaces:
            norm = np.linalg.norm(surface.normal)
            assert abs(norm - 1.0) < 1e-9, (
                f"Normal of surface '{surface.surface_id}' is not unit length: {norm}"
            )

    def test_surface_areas_correct(self):
        L, W, H = 5.0, 4.0, 3.0
        room = define_room_primitive("shoebox", {"L": L, "W": W, "H": H})
        area_map = {s.surface_id: s.area_m2 for s in room.surfaces}
        assert abs(area_map["floor"]   - L * W) < 1e-9
        assert abs(area_map["ceiling"] - L * W) < 1e-9
        assert abs(area_map["wall_x+"] - W * H) < 1e-9
        assert abs(area_map["wall_x-"] - W * H) < 1e-9
        assert abs(area_map["wall_z+"] - L * H) < 1e-9
        assert abs(area_map["wall_z-"] - L * H) < 1e-9


# ---------------------------------------------------------------------------
# test_small_dimension_raises
# ---------------------------------------------------------------------------

class TestSmallDimensionRaises:
    @pytest.mark.parametrize("dim_key,dim_val", [
        ("L", 0.3),
        ("W", 0.3),
        ("H", 0.3),
        ("L", 0.0),
        ("W", 0.49),
    ])
    def test_raises_value_error(self, dim_key, dim_val):
        params = {"L": 5.0, "W": 4.0, "H": 3.0}
        params[dim_key] = dim_val
        with pytest.raises(ValueError, match=r"[Mm]inimum|below|0\.5"):
            define_room_primitive("shoebox", params)

    def test_exactly_at_minimum_does_not_raise(self):
        """Dimension exactly at 0.5 m should not raise."""
        room = define_room_primitive("shoebox", {"L": 0.5, "W": 0.5, "H": 0.5})
        assert room is not None

    def test_unsupported_room_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            define_room_primitive("dome", {"L": 5.0, "W": 4.0, "H": 3.0})


# ---------------------------------------------------------------------------
# test_low_headroom_warns
# ---------------------------------------------------------------------------

class TestLowHeadroomWarns:
    def test_h_below_1_5_warns(self):
        with pytest.warns(UserWarning, match=r"[Hh]eight|1\.2|1\.5"):
            define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 1.2})

    def test_h_at_1_5_does_not_warn(self):
        """H exactly at 1.5 m should not produce a warning."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 1.5})

    def test_h_above_1_5_does_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})


# ---------------------------------------------------------------------------
# test_bounding_volume_shoebox
# ---------------------------------------------------------------------------

class TestBoundingVolumeShoebox:
    def test_aabb_volume_matches_dimensions(self):
        L, W, H = 5.0, 4.0, 3.0
        room = define_room_primitive("shoebox", {"L": L, "W": W, "H": H})
        aabb = generate_bounding_volume(room)
        expected_vol = L * W * H
        assert abs(aabb.volume_m3 - expected_vol) < 0.001, (
            f"AABB volume {aabb.volume_m3:.6f} != expected {expected_vol:.6f}"
        )

    def test_aabb_type(self):
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        aabb = generate_bounding_volume(room)
        assert isinstance(aabb, AABB)

    def test_aabb_min_corner_is_origin(self):
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        aabb = generate_bounding_volume(room)
        assert np.allclose(aabb.min_corner, [0.0, 0.0, 0.0])

    def test_aabb_warn_small_volume(self):
        """Volume < 10 m³ should trigger a UserWarning."""
        room = define_room_primitive("shoebox", {"L": 1.0, "W": 1.0, "H": 1.0})
        with pytest.warns(UserWarning, match=r"[Mm]inimum|10"):
            generate_bounding_volume(room)

    def test_aabb_warn_large_volume(self):
        """Volume > 5000 m³ should trigger a UserWarning."""
        room = define_room_primitive("shoebox", {"L": 50.0, "W": 50.0, "H": 3.0})
        with pytest.warns(UserWarning, match=r"[Mm]aximum|5000"):
            generate_bounding_volume(room)

    def test_aabb_no_warn_normal_volume(self):
        """Volume in valid range (10–5000 m³) should not warn."""
        room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            generate_bounding_volume(room)

    def test_aabb_mesh_room(self):
        """generate_bounding_volume for a MeshRoom uses vertex min/max."""
        mesh = _make_tetrahedron()
        aabb = generate_bounding_volume(mesh)
        assert isinstance(aabb, AABB)
        assert np.allclose(aabb.min_corner, [0.0, 0.0, 0.0])
        assert np.allclose(aabb.max_corner, [1.0, 1.0, 1.0])


# ---------------------------------------------------------------------------
# test_manifold_valid
# ---------------------------------------------------------------------------

class TestManifoldValid:
    def test_tetrahedron_is_valid(self):
        mesh = _make_tetrahedron()
        result = validate_manifold(mesh)
        assert result.is_valid is True
        assert result.open_edges == 0
        assert result.degenerate_faces == 0

    def test_result_type(self):
        mesh = _make_tetrahedron()
        result = validate_manifold(mesh)
        assert isinstance(result, MeshValidationResult)

    def test_no_degenerate_faces_in_tetrahedron(self):
        mesh = _make_tetrahedron()
        result = validate_manifold(mesh)
        assert result.degenerate_faces == 0

    def test_shoebox_mesh_is_valid(self):
        """Build a cube (12 triangles) and verify it is valid."""
        # Cube vertices
        verts = np.array([
            [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],  # bottom
            [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],  # top
        ], dtype=np.float64)
        faces = np.array([
            [0, 2, 1], [0, 3, 2],  # bottom
            [4, 5, 6], [4, 6, 7],  # top
            [0, 1, 5], [0, 5, 4],  # front
            [2, 3, 7], [2, 7, 6],  # back
            [1, 2, 6], [1, 6, 5],  # right
            [0, 4, 7], [0, 7, 3],  # left
        ], dtype=np.int64)
        normals = _compute_normals(verts, faces)
        mesh = MeshRoom(vertices=verts, faces=faces, surface_normals=normals)
        result = validate_manifold(mesh)
        assert result.is_valid is True


# ---------------------------------------------------------------------------
# test_manifold_invalid
# ---------------------------------------------------------------------------

class TestManifoldInvalid:
    def test_open_edge_makes_invalid(self):
        """Remove one face from tetrahedron to create open edges."""
        mesh = _make_tetrahedron()
        broken_faces = mesh.faces[:3].copy()
        broken_normals = mesh.surface_normals[:3].copy()
        broken_mesh = MeshRoom(
            vertices=mesh.vertices,
            faces=broken_faces,
            surface_normals=broken_normals,
        )
        result = validate_manifold(broken_mesh)
        assert result.is_valid is False
        assert result.open_edges > 0

    def test_degenerate_face_detected(self):
        """A face with all vertices at the same point has zero area."""
        mesh = _make_tetrahedron()
        # Inject a degenerate face by duplicating vertex 0
        extra_verts = np.vstack([
            mesh.vertices,
            mesh.vertices[0],  # index 4 = duplicate of 0
        ])
        degen_face = np.array([[0, 0, 4]], dtype=np.int64)  # zero-area triangle
        all_faces = np.vstack([mesh.faces, degen_face])
        # Compute normal for degenerate face (will be zero, but we supply placeholder)
        placeholder_normal = np.array([[0.0, 0.0, 1.0]])
        all_normals = np.vstack([mesh.surface_normals, placeholder_normal])
        broken_mesh = MeshRoom(
            vertices=extra_verts,
            faces=all_faces,
            surface_normals=all_normals,
        )
        result = validate_manifold(broken_mesh)
        assert result.degenerate_faces >= 1

    def test_open_edge_count_nonzero(self):
        mesh = _make_tetrahedron()
        broken_faces = mesh.faces[:2].copy()
        broken_normals = mesh.surface_normals[:2].copy()
        broken_mesh = MeshRoom(
            vertices=mesh.vertices,
            faces=broken_faces,
            surface_normals=broken_normals,
        )
        result = validate_manifold(broken_mesh)
        assert result.open_edges > 0
