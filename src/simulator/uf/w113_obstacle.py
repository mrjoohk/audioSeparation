"""
W100000 Spatial Simulator — UF-W113 Obstacle Placement
Implements UF-W113-01 through UF-W113-04.

UF-W113-01: place_obstacle_objects
UF-W113-02: tag_acoustic_roles
UF-W113-03: check_collisions
UF-W113-04: serialize_obstacle_layout
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from simulator.types import (
    AABB,
    AcousticRole,
    ObjectSpec,
    ObstacleLayout,
    PlacedObject,
)

# Minimum clearance from walls (m)
_WALL_CLEARANCE_M: float = 0.3
# Maximum rejection-sampling attempts per object
_MAX_PLACEMENT_ATTEMPTS: int = 100

# Default acoustic role mapping by object type
_DEFAULT_ROLE_MAP: Dict[str, AcousticRole] = {
    "partition": "occluding",
    "chair":     "absorptive",
    "table":     "reflective",
}


# ---------------------------------------------------------------------------
# UF-W113-01: place_obstacle_objects
# ---------------------------------------------------------------------------

def place_obstacle_objects(
    room_bbox: AABB,
    object_specs: List[ObjectSpec],
    seed: int,
) -> ObstacleLayout:
    """
    Place a list of ObjectSpec instances into a room using rejection sampling.

    Strategy
    --------
    Each object is randomly positioned within room_bbox with a minimum 0.3 m
    margin from all walls.  Positions are rejected if the candidate AABB
    overlaps with any already-placed object.  Up to 100 attempts are made per
    object; if placement fails a UserWarning is issued and the object is skipped.

    Parameters
    ----------
    room_bbox : AABB
        Room bounding box.
    object_specs : list of ObjectSpec
        Objects to place (each may appear multiple times if the list repeats it).
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    ObstacleLayout (list of PlacedObject)
    """
    rng = np.random.default_rng(seed)
    layout: ObstacleLayout = []

    for idx, spec in enumerate(object_specs):
        half = np.asarray(spec.size, dtype=np.float64) / 2.0

        # Compute valid position range (object centre must be this far from walls)
        lo = room_bbox.min_corner + _WALL_CLEARANCE_M + half
        hi = room_bbox.max_corner - _WALL_CLEARANCE_M - half

        if np.any(lo >= hi):
            warnings.warn(
                f"Object '{spec.object_type}' (index {idx}) cannot fit in the room "
                f"with {_WALL_CLEARANCE_M} m wall clearance; skipping.",
                UserWarning,
                stacklevel=2,
            )
            continue

        placed = False
        for _attempt in range(_MAX_PLACEMENT_ATTEMPTS):
            candidate_pos = rng.uniform(lo, hi)
            rotation_y = float(rng.uniform(0.0, 2.0 * np.pi))

            candidate = PlacedObject(
                object_id=f"{spec.object_type}_{idx}",
                object_type=spec.object_type,
                position=candidate_pos.astype(np.float64),
                size=np.asarray(spec.size, dtype=np.float64),
                rotation_y=rotation_y,
                acoustic_role=spec.acoustic_role,
            )

            if not _overlaps_any(candidate, layout):
                layout.append(candidate)
                placed = True
                break

        if not placed:
            warnings.warn(
                f"Object '{spec.object_type}' (index {idx}) could not be placed "
                f"after {_MAX_PLACEMENT_ATTEMPTS} attempts; room may be too crowded.",
                UserWarning,
                stacklevel=2,
            )

    return layout


def _overlaps_any(candidate: PlacedObject, layout: ObstacleLayout) -> bool:
    """Return True if candidate AABB overlaps any placed object's AABB."""
    for placed in layout:
        if _aabb_overlap(candidate.aabb, placed.aabb):
            return True
    return False


def _aabb_overlap(a: AABB, b: AABB, clearance: float = 0.0) -> bool:
    """
    Return True if two AABBs overlap (with optional clearance margin).

    With clearance > 0, the AABBs must be at least `clearance` apart to
    be considered non-overlapping.
    """
    for dim in range(3):
        if (a.max_corner[dim] + clearance <= b.min_corner[dim] or
                b.max_corner[dim] + clearance <= a.min_corner[dim]):
            return False
    return True


# ---------------------------------------------------------------------------
# UF-W113-02: tag_acoustic_roles
# ---------------------------------------------------------------------------

def tag_acoustic_roles(
    placed_objects: ObstacleLayout,
    role_map: Optional[Dict[str, AcousticRole]] = None,
) -> ObstacleLayout:
    """
    Assign acoustic roles to placed objects based on their object_type.

    Parameters
    ----------
    placed_objects : ObstacleLayout
    role_map : dict {object_type → AcousticRole}, optional
        Defaults to {"partition": "occluding", "chair": "absorptive",
        "table": "reflective"}.
        Unknown types → "reflective" + UserWarning.

    Returns
    -------
    ObstacleLayout (new list with updated acoustic_role fields)
    """
    effective_map = _DEFAULT_ROLE_MAP.copy()
    if role_map is not None:
        effective_map.update(role_map)

    result: ObstacleLayout = []
    for obj in placed_objects:
        if obj.object_type not in effective_map:
            warnings.warn(
                f"Object type '{obj.object_type}' has no role mapping; "
                f"assigning 'reflective'.",
                UserWarning,
                stacklevel=2,
            )
            role: AcousticRole = "reflective"
        else:
            role = effective_map[obj.object_type]

        updated = PlacedObject(
            object_id=obj.object_id,
            object_type=obj.object_type,
            position=obj.position.copy(),
            size=obj.size.copy(),
            rotation_y=obj.rotation_y,
            acoustic_role=role,
        )
        result.append(updated)

    return result


# ---------------------------------------------------------------------------
# UF-W113-03: check_collisions
# ---------------------------------------------------------------------------

def check_collisions(
    layout: ObstacleLayout,
    room_bbox: AABB,
    min_clearance_m: float = 0.3,
) -> dict:
    """
    Check for inter-object and object-wall collisions in an ObstacleLayout.

    Each object is tested:
    1. Against every other object (pairwise AABB overlap with clearance margin).
    2. Against the 6 room walls (object must be at least min_clearance_m from each wall).

    Returns
    -------
    dict with keys:
        "n_violations" : int
        "violating_pairs" : List[Tuple[str, str]]
            Each entry is (object_id_A, object_id_B) or (object_id, "wall").
    """
    violating_pairs: List[Tuple[str, str]] = []

    # Pairwise object-object check
    for i in range(len(layout)):
        for j in range(i + 1, len(layout)):
            a = layout[i]
            b = layout[j]
            if _aabb_overlap(a.aabb, b.aabb, clearance=min_clearance_m):
                violating_pairs.append((a.object_id, b.object_id))

    # Object-wall check
    for obj in layout:
        aabb = obj.aabb
        # Check each face: object min/max vs room min/max
        for dim in range(3):
            if aabb.min_corner[dim] < room_bbox.min_corner[dim] + min_clearance_m:
                violating_pairs.append((obj.object_id, "wall"))
                break
            if aabb.max_corner[dim] > room_bbox.max_corner[dim] - min_clearance_m:
                violating_pairs.append((obj.object_id, "wall"))
                break

    return {
        "n_violations": len(violating_pairs),
        "violating_pairs": violating_pairs,
    }


# ---------------------------------------------------------------------------
# UF-W113-04: serialize_obstacle_layout
# ---------------------------------------------------------------------------

def serialize_obstacle_layout(layout: ObstacleLayout, output_path: str) -> dict:
    """
    Serialize an ObstacleLayout to a JSON file.

    Parameters
    ----------
    layout : ObstacleLayout
    output_path : str
        Destination file path. Parent directories are created if needed.

    Returns
    -------
    dict
        The serialized representation (also written to file).
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = [
        {
            "object_id":    obj.object_id,
            "object_type":  obj.object_type,
            "position":     obj.position.tolist(),
            "size":         obj.size.tolist(),
            "rotation_y":   obj.rotation_y,
            "acoustic_role": obj.acoustic_role,
        }
        for obj in layout
    ]

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(serialized, fh, indent=2)

    return {"objects": serialized}


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    print("=== UF-W113 smoke test ===")

    room_bbox = AABB(
        min_corner=np.array([0.0, 0.0, 0.0]),
        max_corner=np.array([10.0, 3.0, 8.0]),
    )

    specs = [
        ObjectSpec(object_type="chair",     size=np.array([0.5, 0.9, 0.5])),
        ObjectSpec(object_type="table",     size=np.array([1.2, 0.75, 0.8])),
        ObjectSpec(object_type="partition", size=np.array([0.1, 2.0, 1.5])),
    ]

    layout = place_obstacle_objects(room_bbox, specs, seed=0)
    print(f"Placed {len(layout)} objects.")
    for obj in layout:
        print(f"  {obj.object_id}: pos={obj.position}, role={obj.acoustic_role}")

    tagged = tag_acoustic_roles(layout)
    print("Tagged roles:")
    for obj in tagged:
        print(f"  {obj.object_id}: {obj.acoustic_role}")

    col = check_collisions(tagged, room_bbox)
    print(f"Collision check: n_violations={col['n_violations']}")

    with tempfile.TemporaryDirectory() as tmpdir:
        out = os.path.join(tmpdir, "layout.json")
        exported = serialize_obstacle_layout(tagged, out)
        print(f"Exported {len(exported['objects'])} objects to JSON.")
        assert Path(out).exists()

    print("All smoke tests passed.")
