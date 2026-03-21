"""
W100000 Spatial Simulator — UF-W131 Source Trajectory Generation
Implements UF-W131-01 through UF-W131-04.

UF-W131-01: generate_source_trajectory
UF-W131-02: compute_velocity_orientation
UF-W131-03: enforce_room_constraints
UF-W131-04: export_trajectory_json
"""
from __future__ import annotations

import json
import math
import os
import sys
import warnings
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from simulator.types import (
    AABB,
    SourceTrajectory,
    TickState,
)

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------
MAX_SOURCE_SPEED_MS: float = 2.0
MIN_WALL_DIST_M: float = 0.5


# ---------------------------------------------------------------------------
# UF-W131-03: enforce_room_constraints
# ---------------------------------------------------------------------------

def enforce_room_constraints(
    positions: np.ndarray,
    room_bbox: AABB,
    min_wall_dist_m: float = MIN_WALL_DIST_M,
) -> np.ndarray:
    """
    Clamp positions to [min_corner + margin, max_corner - margin].

    Parameters
    ----------
    positions : float[T×3]
    room_bbox : AABB
    min_wall_dist_m : float
        Minimum distance from each wall.

    Returns
    -------
    constrained : float[T×3]
    """
    positions = np.asarray(positions, dtype=np.float64)
    lo = room_bbox.min_corner + min_wall_dist_m
    hi = room_bbox.max_corner - min_wall_dist_m
    # Safety: ensure lo < hi
    lo = np.minimum(lo, (room_bbox.min_corner + room_bbox.max_corner) / 2.0)
    hi = np.maximum(hi, (room_bbox.min_corner + room_bbox.max_corner) / 2.0)
    return np.clip(positions, lo, hi)


# ---------------------------------------------------------------------------
# UF-W131-02: compute_velocity_orientation
# ---------------------------------------------------------------------------

def compute_velocity_orientation(
    positions: np.ndarray,
    tick_rate_hz: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute per-tick velocities and yaw orientations from position array.

    velocities[i] = (positions[i+1] - positions[i]) * tick_rate_hz
    velocities[-1] = velocities[-2]  (repeat last)
    orientations[i] = atan2(vx[i], vz[i])  (yaw, Y-up convention)

    Warns and clamps if any |velocity| > 2.0 m/s.

    Returns
    -------
    velocities : float[T×3]
    orientations : float[T]
    """
    positions = np.asarray(positions, dtype=np.float64)
    T = len(positions)

    velocities = np.zeros((T, 3), dtype=np.float64)
    if T > 1:
        velocities[:-1] = (positions[1:] - positions[:-1]) * tick_rate_hz
        velocities[-1] = velocities[-2]
    # else single tick: velocity stays zero

    speeds = np.linalg.norm(velocities, axis=1)
    over_limit = speeds > MAX_SOURCE_SPEED_MS
    if np.any(over_limit):
        n_over = int(np.sum(over_limit))
        max_speed = float(np.max(speeds))
        warnings.warn(
            f"compute_velocity_orientation: {n_over} tick(s) exceed max speed "
            f"({MAX_SOURCE_SPEED_MS} m/s). Max observed: {max_speed:.4f} m/s. "
            "Clamping velocities.",
            UserWarning,
            stacklevel=2,
        )
        # Clamp magnitude while preserving direction
        scale = np.where(over_limit, MAX_SOURCE_SPEED_MS / (speeds + 1e-12), 1.0)
        velocities = velocities * scale[:, np.newaxis]

    # Yaw: atan2(vx, vz) — heading in XZ plane
    orientations = np.arctan2(velocities[:, 0], velocities[:, 2])

    return velocities, orientations


# ---------------------------------------------------------------------------
# Internal helpers for motion types
# ---------------------------------------------------------------------------

def _random_point_in_bbox(rng: np.random.Generator, bbox: AABB, margin: float) -> np.ndarray:
    """Sample a random point strictly inside the bbox with margin."""
    lo = bbox.min_corner + margin
    hi = bbox.max_corner - margin
    lo = np.minimum(lo, (bbox.min_corner + bbox.max_corner) / 2.0)
    hi = np.maximum(hi, lo)
    return rng.uniform(lo, hi).astype(np.float64)


def _build_static_positions(
    n_ticks: int,
    position: np.ndarray,
) -> np.ndarray:
    return np.tile(position, (n_ticks, 1))


def _build_linear_positions(
    n_ticks: int,
    start: np.ndarray,
    end: np.ndarray,
) -> np.ndarray:
    if n_ticks == 1:
        return start[np.newaxis, :]
    t = np.linspace(0.0, 1.0, n_ticks)
    return (start[np.newaxis, :] * (1.0 - t[:, np.newaxis]) +
            end[np.newaxis, :] * t[:, np.newaxis])


def _build_random_walk_positions(
    n_ticks: int,
    bbox: AABB,
    tick_rate_hz: float,
    rng: np.random.Generator,
    start: Optional[np.ndarray] = None,
    max_speed_ms: float = 1.5,
) -> np.ndarray:
    """
    Brownian motion with velocity capping and wall reflection.
    """
    margin = MIN_WALL_DIST_M
    lo = bbox.min_corner + margin
    hi = bbox.max_corner - margin
    lo = np.minimum(lo, (bbox.min_corner + bbox.max_corner) / 2.0)
    hi = np.maximum(hi, lo)

    if start is None:
        pos = rng.uniform(lo, hi).astype(np.float64)
    else:
        pos = np.clip(start.astype(np.float64), lo, hi)

    # Velocity step std: target ~0.3 m/s RMS
    dt = 1.0 / tick_rate_hz
    step_std = 0.3 * math.sqrt(dt)

    positions = np.empty((n_ticks, 3), dtype=np.float64)
    positions[0] = pos
    velocity = np.zeros(3, dtype=np.float64)

    for i in range(1, n_ticks):
        # Random acceleration
        accel = rng.normal(0.0, step_std, size=3)
        velocity = velocity * 0.85 + accel  # damped random walk

        # Cap speed
        speed = np.linalg.norm(velocity)
        if speed > max_speed_ms:
            velocity = velocity * (max_speed_ms / speed)

        new_pos = pos + velocity * dt

        # Wall reflection
        for dim in range(3):
            if new_pos[dim] < lo[dim]:
                new_pos[dim] = lo[dim] + (lo[dim] - new_pos[dim])
                velocity[dim] = -velocity[dim]
            elif new_pos[dim] > hi[dim]:
                new_pos[dim] = hi[dim] - (new_pos[dim] - hi[dim])
                velocity[dim] = -velocity[dim]

        new_pos = np.clip(new_pos, lo, hi)
        positions[i] = new_pos
        pos = new_pos

    return positions


def _build_waypoint_positions(
    n_ticks: int,
    waypoints: np.ndarray,
) -> np.ndarray:
    """
    Interpolate linearly through a sequence of waypoints.
    """
    waypoints = np.asarray(waypoints, dtype=np.float64)
    n_wp = len(waypoints)
    if n_wp == 1:
        return np.tile(waypoints[0], (n_ticks, 1))

    # Evenly distribute ticks across segments
    segment_fracs = np.linspace(0.0, float(n_wp - 1), n_ticks)
    seg_idx = np.floor(segment_fracs).astype(int)
    seg_frac = segment_fracs - seg_idx

    seg_idx = np.clip(seg_idx, 0, n_wp - 2)
    seg_frac = np.clip(seg_frac, 0.0, 1.0)

    positions = (
        waypoints[seg_idx] * (1.0 - seg_frac[:, np.newaxis]) +
        waypoints[seg_idx + 1] * seg_frac[:, np.newaxis]
    )
    return positions


def _build_conversational_positions(
    n_ticks: int,
    bbox: AABB,
    tick_rate_hz: float,
    rng: np.random.Generator,
    n_speakers: int = 2,
    min_static_s: float = 1.0,
    max_static_s: float = 4.0,
) -> np.ndarray:
    """
    Alternating static segments (speaker turns).
    Each turn: a fixed position for a random duration.
    """
    margin = MIN_WALL_DIST_M
    positions = np.empty((n_ticks, 3), dtype=np.float64)

    speaker_positions = [
        _random_point_in_bbox(rng, bbox, margin) for _ in range(n_speakers)
    ]

    tick = 0
    speaker = 0
    while tick < n_ticks:
        dur_s = rng.uniform(min_static_s, max_static_s)
        dur_ticks = max(1, int(round(dur_s * tick_rate_hz)))
        end = min(tick + dur_ticks, n_ticks)
        positions[tick:end] = speaker_positions[speaker]
        tick = end
        speaker = (speaker + 1) % n_speakers

    return positions


# ---------------------------------------------------------------------------
# UF-W131-01: generate_source_trajectory
# ---------------------------------------------------------------------------

def generate_source_trajectory(
    motion_type: str,
    room_bbox: AABB,
    duration_s: float,
    tick_rate_hz: float = 50.0,
    seed: int = 42,
    source_id: str = "source_0",
    **kwargs,
) -> SourceTrajectory:
    """
    Generate a SourceTrajectory for a given motion type.

    Parameters
    ----------
    motion_type : str
        One of: "static", "linear", "random_walk", "waypoint", "conversational"
    room_bbox : AABB
        Room bounding box.
    duration_s : float
        Total duration in seconds.
    tick_rate_hz : float
        Simulation tick rate (default 50 Hz).
    seed : int
        RNG seed for reproducibility.
    source_id : str
        Identifier string for the returned SourceTrajectory.
    **kwargs :
        motion-type-specific arguments (see below).

    Keyword arguments by motion_type
    ---------------------------------
    static:
        position (array[3], optional) — fixed position; random if omitted.
    linear:
        start (array[3], optional), end (array[3], optional) — random if omitted.
    random_walk:
        start (array[3], optional) — initial position.
        max_speed_ms (float, optional) — default 1.5.
    waypoint:
        waypoints (list/array of shape [K×3]) — required.
    conversational:
        n_speakers (int, optional) — default 2.
        min_static_s (float, optional) — default 1.0.
        max_static_s (float, optional) — default 4.0.

    Returns
    -------
    SourceTrajectory
    """
    rng = np.random.default_rng(seed)
    n_ticks = round(duration_s * tick_rate_hz) + 1
    margin = MIN_WALL_DIST_M

    if motion_type == "static":
        position = kwargs.get("position", None)
        if position is None:
            position = _random_point_in_bbox(rng, room_bbox, margin)
        else:
            position = np.asarray(position, dtype=np.float64)
        positions = _build_static_positions(n_ticks, position)

    elif motion_type == "linear":
        start = kwargs.get("start", None)
        end = kwargs.get("end", None)
        if start is None:
            start = _random_point_in_bbox(rng, room_bbox, margin)
        else:
            start = np.asarray(start, dtype=np.float64)
        if end is None:
            end = _random_point_in_bbox(rng, room_bbox, margin)
        else:
            end = np.asarray(end, dtype=np.float64)
        positions = _build_linear_positions(n_ticks, start, end)

    elif motion_type == "random_walk":
        start = kwargs.get("start", None)
        if start is not None:
            start = np.asarray(start, dtype=np.float64)
        max_speed_ms = float(kwargs.get("max_speed_ms", 1.5))
        positions = _build_random_walk_positions(
            n_ticks, room_bbox, tick_rate_hz, rng,
            start=start, max_speed_ms=max_speed_ms,
        )

    elif motion_type == "waypoint":
        waypoints = kwargs.get("waypoints", None)
        if waypoints is None:
            raise ValueError("motion_type='waypoint' requires 'waypoints' kwarg.")
        waypoints = np.asarray(waypoints, dtype=np.float64)
        positions = _build_waypoint_positions(n_ticks, waypoints)

    elif motion_type == "conversational":
        n_speakers = int(kwargs.get("n_speakers", 2))
        min_static_s = float(kwargs.get("min_static_s", 1.0))
        max_static_s = float(kwargs.get("max_static_s", 4.0))
        positions = _build_conversational_positions(
            n_ticks, room_bbox, tick_rate_hz, rng,
            n_speakers=n_speakers,
            min_static_s=min_static_s,
            max_static_s=max_static_s,
        )

    else:
        raise ValueError(
            f"Unknown motion_type '{motion_type}'. "
            "Choose from: static, linear, random_walk, waypoint, conversational."
        )

    # Enforce room constraints
    positions = enforce_room_constraints(positions, room_bbox, margin)

    # Compute velocities and orientations
    velocities, orientations = compute_velocity_orientation(positions, tick_rate_hz)

    # Build TickState list
    dt = 1.0 / tick_rate_hz
    ticks: List[TickState] = []
    for i in range(n_ticks):
        ticks.append(TickState(
            tick_id=i,
            timestamp_s=float(i * dt),
            position=positions[i].copy(),
            velocity=velocities[i].copy(),
            orientation=float(orientations[i]),
        ))

    return SourceTrajectory(
        source_id=source_id,
        ticks=ticks,
        tick_rate_hz=tick_rate_hz,
    )


# ---------------------------------------------------------------------------
# UF-W131-04: export_trajectory_json
# ---------------------------------------------------------------------------

def export_trajectory_json(
    trajectory: SourceTrajectory,
    output_path: str,
) -> dict:
    """
    Serialize a SourceTrajectory to JSON.

    Each entry: {tick_id, timestamp_s, position, velocity, orientation}

    Returns the dict that was written.
    """
    records = []
    for ts in trajectory.ticks:
        records.append({
            "tick_id": ts.tick_id,
            "timestamp_s": float(ts.timestamp_s),
            "position": ts.position.tolist(),
            "velocity": ts.velocity.tolist(),
            "orientation": float(ts.orientation),
        })

    data = {
        "source_id": trajectory.source_id,
        "tick_rate_hz": trajectory.tick_rate_hz,
        "n_ticks": len(trajectory.ticks),
        "ticks": records,
    }

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    return data


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W131 smoke test ===")

    bbox = AABB(
        min_corner=np.array([0.0, 0.0, 0.0]),
        max_corner=np.array([6.0, 3.0, 5.0]),
    )

    for mtype in ["static", "linear", "random_walk", "conversational"]:
        traj = generate_source_trajectory(mtype, bbox, duration_s=2.0, seed=42)
        n = round(2.0 * 50.0) + 1
        assert len(traj.ticks) == n, f"Expected {n} ticks, got {len(traj.ticks)}"
        for ts in traj.ticks:
            assert bbox.contains(ts.position, margin=MIN_WALL_DIST_M), (
                f"{mtype}: position {ts.position} outside room margin at tick {ts.tick_id}"
            )
        print(f"  {mtype}: OK ({n} ticks)")

    # waypoint
    wps = np.array([[1.0, 1.0, 1.0], [3.0, 1.0, 2.0], [5.0, 1.0, 4.0]])
    traj_wp = generate_source_trajectory("waypoint", bbox, 2.0, waypoints=wps, seed=42)
    assert np.allclose(traj_wp.ticks[0].position, wps[0], atol=0.01)
    print("  waypoint: OK")

    # export
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = tf.name
    data = export_trajectory_json(traj_wp, tmp)
    assert data["n_ticks"] == len(traj_wp.ticks)
    os.unlink(tmp)
    print("  export_trajectory_json: OK")

    # compute_velocity_orientation clamp test
    positions = np.zeros((3, 3))
    positions[1] = np.array([10.0, 0.0, 0.0])  # 10 m jump at 50 Hz → 500 m/s
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        vels, oris = compute_velocity_orientation(positions, 50.0)
    assert len(caught) > 0, "Expected warning for velocity clamp"
    speeds = np.linalg.norm(vels, axis=1)
    assert np.all(speeds <= MAX_SOURCE_SPEED_MS + 1e-9), f"Speed not clamped: {speeds}"
    print("  velocity clamp: OK")

    print("All UF-W131 smoke tests passed.")
