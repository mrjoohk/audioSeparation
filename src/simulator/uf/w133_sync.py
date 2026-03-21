"""
W100000 Spatial Simulator — UF-W133 Scene Tick Synchronization
Implements UF-W133-01 through UF-W133-04.

UF-W133-01: synchronize_scene_ticks
UF-W133-02: update_transform_graph
UF-W133-03: create_event_timeline
UF-W133-04: validate_temporal_alignment
"""
from __future__ import annotations

import os
import sys
import warnings
from typing import Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from simulator.types import (
    AABB,
    ArrayConfig,
    MaterialMap,
    ObstacleLayout,
    ReceiverState,
    ReceiverTrajectory,
    RoomGeometry,
    SceneState,
    SourceState,
    SourceTrajectory,
    Transform4x4,
)


# ---------------------------------------------------------------------------
# Internal: assemble a single SceneState from trajectory ticks
# ---------------------------------------------------------------------------

def _assemble_scene_state(
    tick_id: int,
    src_trajectories: List[SourceTrajectory],
    rec_trajectories: List[ReceiverTrajectory],
    room: RoomGeometry,
    obstacles: ObstacleLayout,
    materials: MaterialMap,
) -> SceneState:
    """
    Build a SceneState for the given tick_id from trajectory lists.

    Falls back to last tick if tick_id > trajectory length.
    """
    sources: List[SourceState] = []
    for traj in src_trajectories:
        ts = traj.at(tick_id)
        sources.append(SourceState(
            source_id=traj.source_id,
            position=ts.position.copy(),
            velocity=ts.velocity.copy(),
            orientation=ts.orientation,
            active=True,
        ))

    receivers: List[ReceiverState] = []
    for traj in rec_trajectories:
        ts = traj.at(tick_id)
        quat = ts.orientation_quat
        if quat is None:
            quat = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
        receivers.append(ReceiverState(
            receiver_id=traj.receiver_id,
            position=ts.position.copy(),
            orientation_quat=quat.copy(),
        ))

    return SceneState(
        tick_id=tick_id,
        room=room,
        sources=sources,
        receivers=receivers,
        materials=materials,
        obstacles=obstacles,
    )


# ---------------------------------------------------------------------------
# UF-W133-01: synchronize_scene_ticks
# ---------------------------------------------------------------------------

def synchronize_scene_ticks(
    src_trajectories: List[SourceTrajectory],
    rec_trajectories: List[ReceiverTrajectory],
    room: RoomGeometry,
    obstacles: ObstacleLayout,
    tick_rate_hz: float = 50.0,
    materials: Optional[MaterialMap] = None,
) -> List[SceneState]:
    """
    Build a SceneState list from tick 0 to max_ticks.

    max_ticks = min(len of all trajectories)

    Parameters
    ----------
    src_trajectories : List[SourceTrajectory]
    rec_trajectories : List[ReceiverTrajectory]
    room : RoomGeometry
    obstacles : ObstacleLayout
    tick_rate_hz : float
    materials : MaterialMap (optional; defaults to empty dict)

    Returns
    -------
    List[SceneState]
    """
    if materials is None:
        materials = {}

    if not src_trajectories and not rec_trajectories:
        return []

    all_lengths: List[int] = []
    for t in src_trajectories:
        all_lengths.append(len(t.ticks))
    for t in rec_trajectories:
        all_lengths.append(len(t.ticks))

    max_ticks = min(all_lengths) if all_lengths else 0

    scene_states: List[SceneState] = []
    for tick_id in range(max_ticks):
        state = _assemble_scene_state(
            tick_id=tick_id,
            src_trajectories=src_trajectories,
            rec_trajectories=rec_trajectories,
            room=room,
            obstacles=obstacles,
            materials=materials,
        )
        scene_states.append(state)

    return scene_states


# ---------------------------------------------------------------------------
# UF-W133-02: update_transform_graph
# ---------------------------------------------------------------------------

def update_transform_graph(scene_state: SceneState) -> Dict[str, Transform4x4]:
    """
    Build a transform graph {entity_id: Transform4x4} for all sources and receivers.

    Each Transform4x4 is a 4×4 homogeneous matrix with translation only
    (rotation is recorded in SourceState.orientation or ReceiverState.orientation_quat
    but is NOT applied to the full scene matrix here).

    Returns
    -------
    dict mapping entity_id → np.ndarray (4×4, float64)
    """
    transforms: Dict[str, Transform4x4] = {}

    for src in scene_state.sources:
        T = np.eye(4, dtype=np.float64)
        T[0, 3] = float(src.position[0])
        T[1, 3] = float(src.position[1])
        T[2, 3] = float(src.position[2])
        transforms[src.source_id] = T

    for rec in scene_state.receivers:
        T = np.eye(4, dtype=np.float64)
        T[0, 3] = float(rec.position[0])
        T[1, 3] = float(rec.position[1])
        T[2, 3] = float(rec.position[2])
        transforms[rec.receiver_id] = T

    return transforms


# ---------------------------------------------------------------------------
# UF-W133-03: create_event_timeline
# ---------------------------------------------------------------------------

def create_event_timeline(
    source_ids: List[str],
    speech_start_times: List[float],
    speech_end_times: List[float],
    total_ticks: int,
    tick_rate_hz: float,
) -> Dict[str, dict]:
    """
    Create an event timeline mapping source IDs to active tick ranges.

    Parameters
    ----------
    source_ids : List[str]
    speech_start_times : List[float]
        Start time in seconds for each source.
    speech_end_times : List[float]
        End time in seconds for each source.
    total_ticks : int
    tick_rate_hz : float

    Returns
    -------
    dict: {source_id: {"active_ticks": List[int], "start_tick": int, "end_tick": int}}

    Warns if start/end times do not align to tick boundaries.
    """
    timeline: Dict[str, dict] = {}
    dt = 1.0 / tick_rate_hz

    for src_id, t_start, t_end in zip(source_ids, speech_start_times, speech_end_times):
        start_tick_exact = t_start * tick_rate_hz
        end_tick_exact = t_end * tick_rate_hz

        start_tick = int(round(start_tick_exact))
        end_tick = int(round(end_tick_exact))

        # Warn if not aligned
        if abs(start_tick_exact - start_tick) > 0.01:
            warnings.warn(
                f"Source '{src_id}': start_time={t_start:.6f}s does not align to "
                f"tick boundary (tick_rate={tick_rate_hz} Hz). "
                f"Rounding {start_tick_exact:.4f} → {start_tick}.",
                UserWarning,
                stacklevel=2,
            )
        if abs(end_tick_exact - end_tick) > 0.01:
            warnings.warn(
                f"Source '{src_id}': end_time={t_end:.6f}s does not align to "
                f"tick boundary (tick_rate={tick_rate_hz} Hz). "
                f"Rounding {end_tick_exact:.4f} → {end_tick}.",
                UserWarning,
                stacklevel=2,
            )

        start_tick = max(0, start_tick)
        end_tick = min(total_ticks - 1, end_tick)

        active_ticks = list(range(start_tick, end_tick + 1))

        timeline[src_id] = {
            "active_ticks": active_ticks,
            "start_tick": start_tick,
            "end_tick": end_tick,
        }

    return timeline


# ---------------------------------------------------------------------------
# UF-W133-04: validate_temporal_alignment
# ---------------------------------------------------------------------------

def validate_temporal_alignment(
    scene_states: List[SceneState],
    event_timeline: Dict[str, dict],
) -> dict:
    """
    Check that all source active states in scene_states match the event_timeline.

    For each source, verify that it is active at ticks in active_ticks and
    inactive at other ticks.

    Parameters
    ----------
    scene_states : List[SceneState]
    event_timeline : dict {source_id: {"active_ticks": List[int], ...}}

    Returns
    -------
    dict: {"passed": bool, "misaligned_sources": List[str]}
    """
    misaligned: List[str] = []

    for src_id, timeline_entry in event_timeline.items():
        active_set = set(timeline_entry["active_ticks"])

        for state in scene_states:
            tick_id = state.tick_id
            # Find source in scene state
            src_state = None
            for s in state.sources:
                if s.source_id == src_id:
                    src_state = s
                    break

            if src_state is None:
                # Source not present in scene — if it should be active, that's a mismatch
                if tick_id in active_set:
                    if src_id not in misaligned:
                        misaligned.append(src_id)
                continue

            expected_active = tick_id in active_set
            if src_state.active != expected_active:
                if src_id not in misaligned:
                    misaligned.append(src_id)

    passed = len(misaligned) == 0
    return {"passed": passed, "misaligned_sources": misaligned}


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

    from simulator.uf.w131_trajectory import generate_source_trajectory
    from simulator.uf.w132_receiver_trajectory import generate_receiver_trajectory
    from simulator.uf.w111_room_geometry import define_room_primitive, generate_bounding_volume

    print("=== UF-W133 smoke test ===")

    room = define_room_primitive("shoebox", {"L": 6.0, "W": 5.0, "H": 3.0})
    bbox = generate_bounding_volume(room)

    src_traj = generate_source_trajectory("static", bbox, 2.0, seed=42)
    rec_traj = generate_receiver_trajectory("static", bbox, 2.0, seed=42)

    scene_states = synchronize_scene_ticks(
        [src_traj], [rec_traj], room, [], tick_rate_hz=50.0
    )
    n_expected = round(2.0 * 50.0) + 1
    assert len(scene_states) == n_expected, (
        f"Expected {n_expected} states, got {len(scene_states)}"
    )
    print(f"  synchronize_scene_ticks: {len(scene_states)} states OK")

    # update_transform_graph
    tg = update_transform_graph(scene_states[0])
    assert src_traj.source_id in tg
    assert rec_traj.receiver_id in tg
    T = tg[src_traj.source_id]
    assert T.shape == (4, 4)
    print(f"  update_transform_graph: OK, keys={list(tg.keys())}")

    # create_event_timeline
    timeline = create_event_timeline(
        [src_traj.source_id],
        [0.0],
        [2.0],
        total_ticks=n_expected,
        tick_rate_hz=50.0,
    )
    assert src_traj.source_id in timeline
    print(f"  create_event_timeline: OK, active_ticks={len(timeline[src_traj.source_id]['active_ticks'])}")

    # validate_temporal_alignment (all active → should mismatch since sources default active=True)
    result = validate_temporal_alignment(scene_states, timeline)
    print(f"  validate_temporal_alignment: passed={result['passed']}, misaligned={result['misaligned_sources']}")

    print("All UF-W133 smoke tests passed.")
