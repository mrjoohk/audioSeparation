"""
W100000 Spatial Simulator — UF-W115 Scene State Assembly
Implements UF-W115-01 and UF-W115-02.

UF-W115-01: assemble_scene_state
UF-W115-02: serialize_scene_state
"""
from __future__ import annotations

import dataclasses
import json
import warnings
from pathlib import Path
from typing import List, Union

import numpy as np

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from simulator.types import (
    MaterialMap,
    MeshRoom,
    ObstacleLayout,
    ReceiverState,
    ReceiverTrajectory,
    RoomGeometry,
    RoomPrimitive,
    SceneState,
    SourceState,
    SourceTrajectory,
    TickState,
)


# ---------------------------------------------------------------------------
# UF-W115-01: assemble_scene_state
# ---------------------------------------------------------------------------

def assemble_scene_state(
    room: RoomGeometry,
    material_map: MaterialMap,
    obstacles: ObstacleLayout,
    src_trajectories: List[SourceTrajectory],
    rec_trajectories: List[ReceiverTrajectory],
    tick_id: int,
) -> SceneState:
    """
    Assemble a complete SceneState for a given simulation tick.

    Parameters
    ----------
    room : RoomGeometry
        RoomPrimitive or MeshRoom describing the enclosure.
    material_map : MaterialMap
        Surface → MaterialSpec assignments.
    obstacles : ObstacleLayout
        List of placed obstacle objects.
    src_trajectories : list of SourceTrajectory
        Per-source trajectory data.
    rec_trajectories : list of ReceiverTrajectory
        Per-receiver trajectory data.
    tick_id : int
        The tick index to extract state at (clamped if out-of-range).

    Returns
    -------
    SceneState

    Warns
    -----
    UserWarning
        If tick_id exceeds the length of any trajectory.
    UserWarning
        If src_trajectories is empty.
    """
    if not src_trajectories:
        warnings.warn(
            "assemble_scene_state called with no source trajectories; "
            "SceneState will have no sources.",
            UserWarning,
            stacklevel=2,
        )

    # Build SourceState list
    sources: List[SourceState] = []
    for traj in src_trajectories:
        max_tick = len(traj.ticks) - 1
        if tick_id > max_tick:
            warnings.warn(
                f"tick_id={tick_id} exceeds trajectory length for source "
                f"'{traj.source_id}' (max tick {max_tick}); clamping.",
                UserWarning,
                stacklevel=2,
            )
        tick_state: TickState = traj.at(tick_id)
        sources.append(SourceState(
            source_id=traj.source_id,
            position=tick_state.position.copy(),
            velocity=tick_state.velocity.copy(),
            orientation=tick_state.orientation,
            active=True,
        ))

    # Build ReceiverState list
    receivers: List[ReceiverState] = []
    for traj in rec_trajectories:
        max_tick = len(traj.ticks) - 1
        if tick_id > max_tick:
            warnings.warn(
                f"tick_id={tick_id} exceeds trajectory length for receiver "
                f"'{traj.receiver_id}' (max tick {max_tick}); clamping.",
                UserWarning,
                stacklevel=2,
            )
        tick_state = traj.at(tick_id)
        # Use orientation_quat if present; otherwise identity quaternion
        if tick_state.orientation_quat is not None:
            quat = tick_state.orientation_quat.copy()
        else:
            quat = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)

        receivers.append(ReceiverState(
            receiver_id=traj.receiver_id,
            position=tick_state.position.copy(),
            orientation_quat=quat,
            array_config=None,
            is_binaural=False,
        ))

    return SceneState(
        tick_id=tick_id,
        room=room,
        sources=sources,
        receivers=receivers,
        materials=material_map,
        obstacles=obstacles,
    )


# ---------------------------------------------------------------------------
# UF-W115-02: serialize_scene_state
# ---------------------------------------------------------------------------

def serialize_scene_state(state: SceneState, output_path: str) -> dict:
    """
    Serialize a SceneState to a JSON file.

    Parameters
    ----------
    state : SceneState
    output_path : str
        Destination file path. Parent directories are created if needed.

    Returns
    -------
    dict
        The serialized representation (also written to file).
    """
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = _to_serializable(state)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(serialized, fh, indent=2)

    return serialized


# ---------------------------------------------------------------------------
# Recursive serialisation helpers
# ---------------------------------------------------------------------------

def _to_serializable(obj) -> object:
    """
    Recursively convert dataclasses, numpy arrays, and standard types to
    JSON-serialisable Python objects.
    """
    # numpy scalar types
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()

    # Python primitives
    if isinstance(obj, (bool, int, float, str)) or obj is None:
        return obj

    # dataclass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result = {}
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            # Special handling for room (avoid huge vertex dumps for MeshRoom)
            if f.name == "room":
                result[f.name] = _serialize_room(value)
            else:
                result[f.name] = _to_serializable(value)
        return result

    # dict
    if isinstance(obj, dict):
        return {str(k): _to_serializable(v) for k, v in obj.items()}

    # list / tuple
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(item) for item in obj]

    # Fallback: convert to string
    return str(obj)


def _serialize_room(room: RoomGeometry) -> dict:
    """Compact room serialisation — avoid duplicating huge vertex arrays."""
    if isinstance(room, RoomPrimitive):
        return {
            "room_type": room.room_type,
            "dimensions": room.dimensions,
            "surface_ids": room.surface_ids,
            # Surfaces are large; store summary only
            "n_surfaces": len(room.surfaces),
        }
    elif isinstance(room, MeshRoom):
        return {
            "room_type": "mesh",
            "source_file": room.source_file,
            "scale": room.scale,
            "n_vertices": int(room.vertices.shape[0]),
            "n_faces": int(room.faces.shape[0]),
        }
    else:
        return {"room_type": str(type(room).__name__)}


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    from simulator.types import (
        RoomPrimitive,
        MaterialSpec,
        PlacedObject,
        SourceTrajectory,
        ReceiverTrajectory,
        TickState,
    )
    from simulator.uf.w111_room_geometry import define_room_primitive
    from simulator.uf.w112_material import MaterialDB, assign_materials

    print("=== UF-W115 smoke test ===")

    # Room
    room = define_room_primitive("shoebox", {"L": 6.0, "W": 5.0, "H": 3.0})

    # Materials
    db = MaterialDB.instance()
    surface_ids = room.surface_ids
    assignments = {sid: "concrete" for sid in surface_ids}
    assignments["floor"] = "carpet"
    mat_map = assign_materials(surface_ids, assignments, db)

    # No obstacles
    obstacles = []

    # Source trajectory (2 ticks)
    t0 = TickState(
        tick_id=0,
        timestamp_s=0.0,
        position=np.array([2.0, 1.5, 2.0], dtype=np.float64),
        velocity=np.zeros(3, dtype=np.float64),
        orientation=0.0,
    )
    t1 = TickState(
        tick_id=1,
        timestamp_s=0.02,
        position=np.array([2.1, 1.5, 2.0], dtype=np.float64),
        velocity=np.array([0.5, 0.0, 0.0], dtype=np.float64),
        orientation=0.0,
    )
    src_traj = SourceTrajectory(source_id="src_0", ticks=[t0, t1], tick_rate_hz=50.0)

    # Receiver trajectory (2 ticks)
    r0 = TickState(
        tick_id=0,
        timestamp_s=0.0,
        position=np.array([4.0, 1.5, 3.0], dtype=np.float64),
        velocity=np.zeros(3, dtype=np.float64),
        orientation=0.0,
        orientation_quat=np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64),
    )
    r1 = TickState(
        tick_id=1,
        timestamp_s=0.02,
        position=np.array([4.0, 1.5, 3.0], dtype=np.float64),
        velocity=np.zeros(3, dtype=np.float64),
        orientation=0.0,
        orientation_quat=np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64),
    )
    rec_traj = ReceiverTrajectory(receiver_id="rec_0", ticks=[r0, r1], tick_rate_hz=50.0)

    # assemble at tick 0
    state = assemble_scene_state(room, mat_map, obstacles, [src_traj], [rec_traj], tick_id=0)
    print(f"SceneState tick_id={state.tick_id}, sources={len(state.sources)}, receivers={len(state.receivers)}")
    assert state.tick_id == 0
    assert len(state.sources) == 1
    assert len(state.receivers) == 1
    assert np.allclose(state.sources[0].position, [2.0, 1.5, 2.0])

    # serialize
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "scene_state.json")
        exported = serialize_scene_state(state, out_path)
        print(f"Exported keys: {list(exported.keys())}")
        assert Path(out_path).exists()
        # roundtrip check
        with open(out_path, "r") as fh:
            loaded = json.load(fh)
        assert loaded["tick_id"] == 0
        print(f"JSON tick_id: {loaded['tick_id']}")
        src_pos = loaded["sources"][0]["position"]
        print(f"Source position from JSON: {src_pos}")
        assert src_pos == [2.0, 1.5, 2.0]

    print("All smoke tests passed.")
