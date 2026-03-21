"""
W100000 Spatial Simulator — UF-W111 Room Geometry
Implements UF-W111-01 through UF-W111-04.

UF-W111-01: define_room_primitive
UF-W111-02: import_mesh_geometry
UF-W111-03: validate_manifold
UF-W111-04: generate_bounding_volume
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Union

import numpy as np

import sys
import os

# Ensure 'src/' is on sys.path so 'simulator.types' is importable.
# This file lives at src/simulator/uf/w111_room_geometry.py
# dirname(__file__) = src/simulator/uf  → '..' → src/simulator → '..' → src
_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from simulator.types import (
    AABB,
    MeshRoom,
    MeshValidationResult,
    RoomPrimitive,
    Surface,
)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class MeshError(Exception):
    """Raised when a loaded mesh is geometrically invalid (e.g. non-manifold)."""


# ---------------------------------------------------------------------------
# UF-W111-01: define_room_primitive
# ---------------------------------------------------------------------------

def define_room_primitive(room_type: str, params: dict) -> RoomPrimitive:
    """
    Build a RoomPrimitive from a named primitive type and parameter dict.

    Supported room_type values
    --------------------------
    "shoebox"  : params = {"L": float, "W": float, "H": float}
    "corridor" : params = {"L": float, "W": float, "H": float}
    "hall"     : params = {"L": float, "W": float, "H": float, "arch_height": float}

    Raises
    ------
    ValueError
        If any required dimension is < 0.5 m or if room_type is unsupported.
    UserWarning
        If H < 1.5 m.
    """
    supported = ("shoebox", "corridor", "hall")
    if room_type not in supported:
        raise ValueError(
            f"Unsupported room_type '{room_type}'. Must be one of {supported}."
        )

    # Extract required dims
    L = float(params.get("L", 0.0))
    W = float(params.get("W", 0.0))
    H = float(params.get("H", 0.0))

    for name, val in [("L", L), ("W", W), ("H", H)]:
        if val < 0.5:
            raise ValueError(
                f"Room dimension '{name}' = {val:.4f} m is below the minimum of 0.5 m."
            )

    if H < 1.5:
        warnings.warn(
            f"Room height H = {H:.4f} m is below 1.5 m; this may be physically implausible.",
            UserWarning,
            stacklevel=2,
        )

    dimensions: dict = {"L": L, "W": W, "H": H}

    if room_type == "hall":
        arch_height = float(params.get("arch_height", H))
        dimensions["arch_height"] = arch_height

    surfaces = _build_shoebox_surfaces(L, W, H)
    surface_ids = [s.surface_id for s in surfaces]

    return RoomPrimitive(
        room_type=room_type,
        dimensions=dimensions,
        surfaces=surfaces,
        surface_ids=surface_ids,
    )


def _build_shoebox_surfaces(L: float, W: float, H: float) -> list:
    """
    Build 6 Surface objects for a shoebox room.

    Coordinate layout (Y-up RH):
      x  ∈ [0, L]
      y  ∈ [0, H]  (vertical)
      z  ∈ [0, W]

    Surface IDs and inward normals (pointing into the room interior):
      floor    : +Y  normal (y=0 face)
      ceiling  : -Y  normal (y=H face)
      wall_x+  : -X  normal (x=L face)
      wall_x-  : +X  normal (x=0 face)
      wall_z+  : -Z  normal (z=W face)
      wall_z-  : +Z  normal (z=0 face)
    """
    surfaces = []

    # floor  (y = 0), normal pointing up (+Y into room)
    floor_verts = np.array([
        [0.0, 0.0, 0.0],
        [L,   0.0, 0.0],
        [L,   0.0, W  ],
        [0.0, 0.0, W  ],
    ], dtype=np.float64)
    surfaces.append(Surface(
        surface_id="floor",
        normal=np.array([0.0, 1.0, 0.0], dtype=np.float64),
        vertices=floor_verts,
        area_m2=float(L * W),
    ))

    # ceiling (y = H), normal pointing down (-Y into room)
    ceiling_verts = np.array([
        [0.0, H, 0.0],
        [L,   H, 0.0],
        [L,   H, W  ],
        [0.0, H, W  ],
    ], dtype=np.float64)
    surfaces.append(Surface(
        surface_id="ceiling",
        normal=np.array([0.0, -1.0, 0.0], dtype=np.float64),
        vertices=ceiling_verts,
        area_m2=float(L * W),
    ))

    # wall_x+ (x = L), normal pointing -X into room
    wall_xp_verts = np.array([
        [L, 0.0, 0.0],
        [L, H,   0.0],
        [L, H,   W  ],
        [L, 0.0, W  ],
    ], dtype=np.float64)
    surfaces.append(Surface(
        surface_id="wall_x+",
        normal=np.array([-1.0, 0.0, 0.0], dtype=np.float64),
        vertices=wall_xp_verts,
        area_m2=float(W * H),
    ))

    # wall_x- (x = 0), normal pointing +X into room
    wall_xm_verts = np.array([
        [0.0, 0.0, 0.0],
        [0.0, H,   0.0],
        [0.0, H,   W  ],
        [0.0, 0.0, W  ],
    ], dtype=np.float64)
    surfaces.append(Surface(
        surface_id="wall_x-",
        normal=np.array([1.0, 0.0, 0.0], dtype=np.float64),
        vertices=wall_xm_verts,
        area_m2=float(W * H),
    ))

    # wall_z+ (z = W), normal pointing -Z into room
    wall_zp_verts = np.array([
        [0.0, 0.0, W],
        [L,   0.0, W],
        [L,   H,   W],
        [0.0, H,   W],
    ], dtype=np.float64)
    surfaces.append(Surface(
        surface_id="wall_z+",
        normal=np.array([0.0, 0.0, -1.0], dtype=np.float64),
        vertices=wall_zp_verts,
        area_m2=float(L * H),
    ))

    # wall_z- (z = 0), normal pointing +Z into room
    wall_zm_verts = np.array([
        [0.0, 0.0, 0.0],
        [L,   0.0, 0.0],
        [L,   H,   0.0],
        [0.0, H,   0.0],
    ], dtype=np.float64)
    surfaces.append(Surface(
        surface_id="wall_z-",
        normal=np.array([0.0, 0.0, 1.0], dtype=np.float64),
        vertices=wall_zm_verts,
        area_m2=float(L * H),
    ))

    return surfaces


# ---------------------------------------------------------------------------
# UF-W111-02: import_mesh_geometry
# ---------------------------------------------------------------------------

def import_mesh_geometry(
    mesh_file: Union[str, Path],
    scale: float = 1.0,
) -> MeshRoom:
    """
    Load a triangle-mesh room from a file using trimesh.

    Parameters
    ----------
    mesh_file : str or Path
        Path to the mesh file (OBJ, PLY, STL, etc.).
    scale : float
        Uniform scale factor applied to all vertices.

    Returns
    -------
    MeshRoom

    Raises
    ------
    IOError
        If the file does not exist.
    ImportError
        If trimesh is not installed.
    MeshError
        If the loaded mesh is non-manifold.
    """
    try:
        import trimesh  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "trimesh is required for import_mesh_geometry. "
            "Install it with: pip install trimesh"
        ) from exc

    mesh_path = Path(mesh_file)
    if not mesh_path.exists():
        raise IOError(f"Mesh file not found: {mesh_path}")

    loaded = trimesh.load(str(mesh_path), force="mesh")

    # Auto-triangulate if not already a Trimesh
    if not isinstance(loaded, trimesh.Trimesh):
        loaded = trimesh.util.concatenate(
            [trimesh.Trimesh(vertices=m.vertices, faces=m.faces)
             for m in loaded.geometry.values()]
            if hasattr(loaded, "geometry") else [loaded]
        )

    # Apply scale
    if scale != 1.0:
        loaded.apply_scale(scale)

    # Check manifold
    if not loaded.is_watertight:
        raise MeshError(
            f"Mesh '{mesh_path.name}' is non-manifold (not watertight). "
            "Repair or replace the mesh before importing."
        )

    vertices = np.array(loaded.vertices, dtype=np.float64)
    faces = np.array(loaded.faces, dtype=np.int64)
    normals = np.array(loaded.face_normals, dtype=np.float64)

    return MeshRoom(
        vertices=vertices,
        faces=faces,
        surface_normals=normals,
        source_file=str(mesh_path.resolve()),
        scale=scale,
    )


# ---------------------------------------------------------------------------
# UF-W111-03: validate_manifold
# ---------------------------------------------------------------------------

def validate_manifold(mesh: MeshRoom) -> MeshValidationResult:
    """
    Validate a MeshRoom for manifold properties.

    Counts
    ------
    open_edges        : edges shared by ≠ 2 faces (should be 0 for closed mesh)
    degenerate_faces  : faces whose area < 1e-6 m²

    Returns
    -------
    MeshValidationResult with is_valid = (open_edges == 0 and degenerate_faces == 0)
    """
    vertices = mesh.vertices
    faces = mesh.faces

    # Build edge → face count map
    edge_face_count: dict = {}
    for face in faces:
        edges = [
            (int(min(face[0], face[1])), int(max(face[0], face[1]))),
            (int(min(face[1], face[2])), int(max(face[1], face[2]))),
            (int(min(face[2], face[0])), int(max(face[2], face[0]))),
        ]
        for e in edges:
            edge_face_count[e] = edge_face_count.get(e, 0) + 1

    open_edges = sum(1 for count in edge_face_count.values() if count != 2)

    # Compute face areas
    degenerate_faces = 0
    for face in faces:
        v0 = vertices[face[0]]
        v1 = vertices[face[1]]
        v2 = vertices[face[2]]
        area = 0.5 * float(np.linalg.norm(np.cross(v1 - v0, v2 - v0)))
        if area < 1e-6:
            degenerate_faces += 1

    is_valid = (open_edges == 0) and (degenerate_faces == 0)

    return MeshValidationResult(
        is_valid=is_valid,
        open_edges=open_edges,
        degenerate_faces=degenerate_faces,
    )


# ---------------------------------------------------------------------------
# UF-W111-04: generate_bounding_volume
# ---------------------------------------------------------------------------

def generate_bounding_volume(room) -> AABB:
    """
    Compute an axis-aligned bounding box for a RoomPrimitive or MeshRoom.

    For RoomPrimitive (shoebox/corridor/hall): use dimensions directly.
    For MeshRoom: min/max over all vertices.

    Issues UserWarning if volume < 10 m³ or > 5000 m³.
    """
    if isinstance(room, RoomPrimitive):
        L = room.dimensions.get("L", 0.0)
        W = room.dimensions.get("W", 0.0)
        H = room.dimensions.get("H", 0.0)
        # Coordinate layout: x∈[0,L], y∈[0,H], z∈[0,W]
        min_corner = np.array([0.0, 0.0, 0.0], dtype=np.float64)
        max_corner = np.array([L, H, W], dtype=np.float64)

    elif isinstance(room, MeshRoom):
        min_corner = np.min(room.vertices, axis=0).astype(np.float64)
        max_corner = np.max(room.vertices, axis=0).astype(np.float64)

    else:
        raise TypeError(
            f"generate_bounding_volume: unsupported room type {type(room).__name__}."
        )

    aabb = AABB(min_corner=min_corner, max_corner=max_corner)

    vol = aabb.volume_m3
    if vol < 10.0:
        warnings.warn(
            f"Room bounding volume {vol:.2f} m³ is below the minimum of 10 m³.",
            UserWarning,
            stacklevel=2,
        )
    elif vol > 5000.0:
        warnings.warn(
            f"Room bounding volume {vol:.2f} m³ exceeds the maximum of 5000 m³.",
            UserWarning,
            stacklevel=2,
        )

    return aabb


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W111 smoke test ===")

    # 1. define_room_primitive — shoebox
    room = define_room_primitive("shoebox", {"L": 5.0, "W": 4.0, "H": 3.0})
    print(f"RoomPrimitive: type={room.room_type}, volume={room.volume_m3} m³")
    print(f"  Surface IDs: {room.surface_ids}")
    assert len(room.surfaces) == 6
    assert abs(room.volume_m3 - 60.0) < 1e-6

    # 2. generate_bounding_volume
    aabb = generate_bounding_volume(room)
    print(f"AABB: min={aabb.min_corner}, max={aabb.max_corner}, vol={aabb.volume_m3:.2f} m³")

    # 3. validate_manifold — tetrahedron (valid)
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
    normals = []
    for f in faces:
        v0, v1, v2 = verts[f[0]], verts[f[1]], verts[f[2]]
        n = np.cross(v1 - v0, v2 - v0)
        normals.append(n / (np.linalg.norm(n) + 1e-12))
    normals_arr = np.array(normals, dtype=np.float64)

    mesh_valid = MeshRoom(vertices=verts, faces=faces, surface_normals=normals_arr)
    result_valid = validate_manifold(mesh_valid)
    print(f"Valid mesh result: {result_valid}")
    assert result_valid.is_valid

    # Invalid mesh: remove one face
    mesh_broken = MeshRoom(vertices=verts, faces=faces[:3], surface_normals=normals_arr[:3])
    result_broken = validate_manifold(mesh_broken)
    print(f"Broken mesh result: {result_broken}")
    assert not result_broken.is_valid

    print("All smoke tests passed.")
