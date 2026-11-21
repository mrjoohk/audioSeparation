"""
W100000 Spatial Simulator — UF-W132 Receiver Trajectory Generation
Implements UF-W132-01 through UF-W132-04.

UF-W132-01: generate_receiver_trajectory
UF-W132-02: generate_head_orientation
UF-W132-03: add_pose_estimation_error
UF-W132-04: export_receiver_trajectory_json
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
    ReceiverTrajectory,
    TickState,
)

MIN_WALL_DIST_M: float = 0.5


# ---------------------------------------------------------------------------
# Quaternion helpers
# ---------------------------------------------------------------------------

def _euler_to_quat(yaw: float, pitch: float, roll: float = 0.0) -> np.ndarray:
    """
    Convert Euler angles (yaw, pitch, roll) in radians to quaternion (x, y, z, w).
    Rotation order: yaw (Y-axis), pitch (X-axis), roll (Z-axis).
    """
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy

    q = np.array([x, y, z, w], dtype=np.float64)
    norm = np.linalg.norm(q)
    if norm > 1e-12:
        q /= norm
    else:
        q = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
    return q


def _normalize_quat(q: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(q)
    if norm < 1e-12:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64)
    return q / norm


# ---------------------------------------------------------------------------
# UF-W132-02: generate_head_orientation
# ---------------------------------------------------------------------------

def generate_head_orientation(
    n_ticks: int,
    orientation_type: str = "wearable",
    sigma_yaw_deg: float = 15.0,
    sigma_pitch_deg: float = 5.0,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate a quaternion sequence for head orientation.

    Parameters
    ----------
    n_ticks : int
    orientation_type : str
        "static" → identity quaternion for all ticks.
        "wearable" → Gaussian random walk on yaw/pitch → quaternion.
    sigma_yaw_deg : float
        Per-tick yaw perturbation std (degrees).
    sigma_pitch_deg : float
        Per-tick pitch perturbation std (degrees).
    seed : int

    Returns
    -------
    orientations : float[T×4] quaternion (x, y, z, w), normalized
    """
    rng = np.random.default_rng(seed)
    orientations = np.zeros((n_ticks, 4), dtype=np.float64)

    if orientation_type == "static":
        orientations[:, 3] = 1.0  # w=1 → identity
        return orientations

    # wearable: Gaussian random walk on Euler angles
    sigma_yaw = math.radians(sigma_yaw_deg)
    sigma_pitch = math.radians(sigma_pitch_deg)

    yaw = 0.0
    pitch = 0.0

    for i in range(n_ticks):
        dyaw = rng.normal(0.0, sigma_yaw)
        dpitch = rng.normal(0.0, sigma_pitch)
        yaw += dyaw
        pitch += dpitch
        # Clamp pitch to ±90°
        pitch = float(np.clip(pitch, -math.pi / 2.0, math.pi / 2.0))
        orientations[i] = _euler_to_quat(yaw, pitch)

    return orientations


# ---------------------------------------------------------------------------
# UF-W132-03: add_pose_estimation_error
# ---------------------------------------------------------------------------

def add_pose_estimation_error(
    orientations_quat: np.ndarray,
    sigma_yaw_deg: float = 2.0,
    sigma_pitch_deg: float = 1.0,
    seed: int = 42,
) -> np.ndarray:
    """
    Add small Gaussian noise to quaternions and renormalize.

    Simulates wearable sensor pose estimation error.

    Parameters
    ----------
    orientations_quat : float[T×4]
    sigma_yaw_deg : float
    sigma_pitch_deg : float
    seed : int

    Returns
    -------
    perturbed : float[T×4], normalized
    """
    rng = np.random.default_rng(seed)
    orientations_quat = np.asarray(orientations_quat, dtype=np.float64)
    T = len(orientations_quat)

    sigma_yaw = math.radians(sigma_yaw_deg)
    sigma_pitch = math.radians(sigma_pitch_deg)

    result = np.empty_like(orientations_quat)
    for i in range(T):
        noise_yaw = rng.normal(0.0, sigma_yaw)
        noise_pitch = rng.normal(0.0, sigma_pitch)
        noise_quat = _euler_to_quat(noise_yaw, noise_pitch)

        # Quaternion multiplication: q * noise_q
        q = orientations_quat[i]
        qx, qy, qz, qw = q
        nx, ny, nz, nw = noise_quat

        rx = qw * nx + qx * nw + qy * nz - qz * ny
        ry = qw * ny - qx * nz + qy * nw + qz * nx
        rz = qw * nz + qx * ny - qy * nx + qz * nw
        rw = qw * nw - qx * nx - qy * ny - qz * nz

        combined = np.array([rx, ry, rz, rw], dtype=np.float64)
        result[i] = _normalize_quat(combined)

    return result


# ---------------------------------------------------------------------------
# Internal: position builders for receiver types
# ---------------------------------------------------------------------------

def _random_point_in_bbox(rng: np.random.Generator, bbox: AABB, margin: float) -> np.ndarray:
    lo = bbox.min_corner + margin
    hi = bbox.max_corner - margin
    lo = np.minimum(lo, (bbox.min_corner + bbox.max_corner) / 2.0)
    hi = np.maximum(hi, lo)
    return rng.uniform(lo, hi).astype(np.float64)


def _clamp_to_bbox(positions: np.ndarray, bbox: AABB, margin: float) -> np.ndarray:
    lo = bbox.min_corner + margin
    hi = bbox.max_corner - margin
    lo = np.minimum(lo, (bbox.min_corner + bbox.max_corner) / 2.0)
    hi = np.maximum(hi, lo)
    return np.clip(positions, lo, hi)


def _build_handheld_positions(
    n_ticks: int,
    bbox: AABB,
    tick_rate_hz: float,
    rng: np.random.Generator,
    max_speed_ms: float = 0.5,
) -> np.ndarray:
    """Slow random walk ≤ 0.5 m/s."""
    margin = MIN_WALL_DIST_M
    lo = bbox.min_corner + margin
    hi = bbox.max_corner - margin
    lo = np.minimum(lo, (bbox.min_corner + bbox.max_corner) / 2.0)
    hi = np.maximum(hi, lo)

    pos = rng.uniform(lo, hi).astype(np.float64)
    dt = 1.0 / tick_rate_hz
    step_std = 0.15 * math.sqrt(dt)

    positions = np.empty((n_ticks, 3), dtype=np.float64)
    positions[0] = pos
    velocity = np.zeros(3, dtype=np.float64)

    for i in range(1, n_ticks):
        accel = rng.normal(0.0, step_std, size=3)
        velocity = velocity * 0.9 + accel
        speed = np.linalg.norm(velocity)
        if speed > max_speed_ms:
            velocity = velocity * (max_speed_ms / speed)
        new_pos = pos + velocity * dt
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


def _build_robot_sweep_positions(
    n_ticks: int,
    bbox: AABB,
    tick_rate_hz: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Systematic sweep: snake pattern in XZ plane at fixed Y height."""
    margin = MIN_WALL_DIST_M
    lo = bbox.min_corner + margin
    hi = bbox.max_corner - margin
    lo = np.minimum(lo, (bbox.min_corner + bbox.max_corner) / 2.0)
    hi = np.maximum(hi, lo)

    # Fixed Y = center height
    y = float((lo[1] + hi[1]) / 2.0)

    t = np.linspace(0.0, 1.0, n_ticks)
    # Snake pattern: oscillate in X while sweeping in Z
    x = lo[0] + (hi[0] - lo[0]) * (0.5 + 0.5 * np.sin(2.0 * math.pi * 2.0 * t))
    z = lo[2] + (hi[2] - lo[2]) * t

    positions = np.stack([x, np.full(n_ticks, y), z], axis=1).astype(np.float64)
    return positions


# ---------------------------------------------------------------------------
# UF-W132-01: generate_receiver_trajectory
# ---------------------------------------------------------------------------

def generate_receiver_trajectory(
    receiver_type: str,
    room_bbox: AABB,
    duration_s: float,
    tick_rate_hz: float = 50.0,
    seed: int = 42,
    receiver_id: str = "receiver_0",
    **kwargs,
) -> ReceiverTrajectory:
    """
    Generate a ReceiverTrajectory for a given receiver type.

    Parameters
    ----------
    receiver_type : str
        One of: "static", "handheld", "wearable", "robot", "array_mounted"
    room_bbox : AABB
    duration_s : float
    tick_rate_hz : float
    seed : int
    receiver_id : str
    **kwargs :
        "position" (array[3]) — fixed position for static/array_mounted.
        "max_speed_ms" (float) — override for handheld.

    Returns
    -------
    ReceiverTrajectory
    """
    rng = np.random.default_rng(seed)
    n_ticks = round(duration_s * tick_rate_hz) + 1
    margin = MIN_WALL_DIST_M
    dt = 1.0 / tick_rate_hz

    add_jitter = False
    sigma_yaw_deg = 15.0
    sigma_pitch_deg = 5.0

    if receiver_type in ("static", "array_mounted"):
        position = kwargs.get("position", None)
        if position is None:
            position = _random_point_in_bbox(rng, room_bbox, margin)
        else:
            position = np.asarray(position, dtype=np.float64)
        positions = np.tile(position, (n_ticks, 1))
        orientations_quat = generate_head_orientation(
            n_ticks, orientation_type="static", seed=seed
        )

    elif receiver_type == "handheld":
        max_speed_ms = float(kwargs.get("max_speed_ms", 0.5))
        positions = _build_handheld_positions(
            n_ticks, room_bbox, tick_rate_hz, rng, max_speed_ms=max_speed_ms
        )
        add_jitter = True
        sigma_yaw_deg = 15.0
        sigma_pitch_deg = 5.0
        orientations_quat = generate_head_orientation(
            n_ticks, orientation_type="wearable",
            sigma_yaw_deg=sigma_yaw_deg, sigma_pitch_deg=sigma_pitch_deg,
            seed=seed + 1,
        )

    elif receiver_type == "wearable":
        # Very slow movement
        positions = _build_handheld_positions(
            n_ticks, room_bbox, tick_rate_hz, rng, max_speed_ms=0.2
        )
        sigma_yaw_deg = 15.0
        sigma_pitch_deg = 5.0
        orientations_quat = generate_head_orientation(
            n_ticks, orientation_type="wearable",
            sigma_yaw_deg=sigma_yaw_deg, sigma_pitch_deg=sigma_pitch_deg,
            seed=seed + 1,
        )

    elif receiver_type == "robot":
        positions = _build_robot_sweep_positions(n_ticks, room_bbox, tick_rate_hz, rng)
        orientations_quat = generate_head_orientation(
            n_ticks, orientation_type="static", seed=seed
        )

    else:
        raise ValueError(
            f"Unknown receiver_type '{receiver_type}'. "
            "Choose from: static, handheld, wearable, robot, array_mounted."
        )

    # Enforce room constraints (explicit static positions are validated, not moved)
    explicit_static = (
        receiver_type in ("static", "array_mounted") and kwargs.get("position") is not None
    )
    if explicit_static:
        if not room_bbox.contains(positions[0]):
            raise ValueError(
                f"Static receiver position {positions[0].tolist()} lies outside the room "
                f"[{room_bbox.min_corner.tolist()}, {room_bbox.max_corner.tolist()}]."
            )
    else:
        positions = _clamp_to_bbox(positions, room_bbox, margin)

    # Compute velocities (finite diff)
    velocities = np.zeros((n_ticks, 3), dtype=np.float64)
    if n_ticks > 1:
        velocities[:-1] = (positions[1:] - positions[:-1]) * tick_rate_hz
        velocities[-1] = velocities[-2]

    # Compute yaw orientation from velocity for the scalar orientation field
    orientations_yaw = np.arctan2(velocities[:, 0], velocities[:, 2])

    # Build TickState list
    ticks: List[TickState] = []
    for i in range(n_ticks):
        ticks.append(TickState(
            tick_id=i,
            timestamp_s=float(i * dt),
            position=positions[i].copy(),
            velocity=velocities[i].copy(),
            orientation=float(orientations_yaw[i]),
            orientation_quat=orientations_quat[i].copy(),
        ))

    return ReceiverTrajectory(
        receiver_id=receiver_id,
        ticks=ticks,
        tick_rate_hz=tick_rate_hz,
    )


# ---------------------------------------------------------------------------
# UF-W132-04: export_receiver_trajectory_json
# ---------------------------------------------------------------------------

def export_receiver_trajectory_json(
    trajectory: ReceiverTrajectory,
    output_path: str,
) -> dict:
    """
    Serialize a ReceiverTrajectory to JSON.

    Returns the dict that was written.
    """
    records = []
    for ts in trajectory.ticks:
        rec = {
            "tick_id": ts.tick_id,
            "timestamp_s": float(ts.timestamp_s),
            "position": ts.position.tolist(),
            "velocity": ts.velocity.tolist(),
            "orientation": float(ts.orientation),
        }
        if ts.orientation_quat is not None:
            rec["orientation_quat"] = ts.orientation_quat.tolist()
        records.append(rec)

    data = {
        "receiver_id": trajectory.receiver_id,
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
    print("=== UF-W132 smoke test ===")

    bbox = AABB(
        min_corner=np.array([0.0, 0.0, 0.0]),
        max_corner=np.array([6.0, 3.0, 5.0]),
    )

    for rtype in ["static", "handheld", "wearable", "robot", "array_mounted"]:
        traj = generate_receiver_trajectory(rtype, bbox, duration_s=2.0, seed=42)
        n = round(2.0 * 50.0) + 1
        assert len(traj.ticks) == n, f"Expected {n} ticks, got {len(traj.ticks)}"
        for ts in traj.ticks:
            assert bbox.contains(ts.position, margin=MIN_WALL_DIST_M), (
                f"{rtype}: position {ts.position} outside room margin at tick {ts.tick_id}"
            )
        print(f"  {rtype}: OK ({n} ticks)")

    # generate_head_orientation
    q_static = generate_head_orientation(10, "static")
    assert q_static.shape == (10, 4)
    assert np.allclose(q_static[:, 3], 1.0)
    print("  head_orientation static: OK")

    q_wear = generate_head_orientation(10, "wearable")
    assert q_wear.shape == (10, 4)
    norms = np.linalg.norm(q_wear, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-9), f"Quaternions not normalized: {norms}"
    print("  head_orientation wearable: OK")

    # add_pose_estimation_error
    q_err = add_pose_estimation_error(q_wear)
    assert q_err.shape == (10, 4)
    norms2 = np.linalg.norm(q_err, axis=1)
    assert np.allclose(norms2, 1.0, atol=1e-9)
    print("  pose_estimation_error: OK")

    # export
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = tf.name
    traj = generate_receiver_trajectory("wearable", bbox, 1.0, seed=42)
    data = export_receiver_trajectory_json(traj, tmp)
    assert data["n_ticks"] == len(traj.ticks)
    os.unlink(tmp)
    print("  export: OK")

    print("All UF-W132 smoke tests passed.")
