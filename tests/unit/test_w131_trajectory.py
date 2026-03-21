"""
Unit tests for UF-W131 Source Trajectory Generation.

Tests:
  - test_static_inside_room
  - test_linear_trajectory_length
  - test_random_walk_bounds
  - test_waypoint_interpolation
  - test_reproducibility
  - test_velocity_clamp
"""
from __future__ import annotations

import math
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

# Path setup to find simulator package
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from simulator.types import AABB
from simulator.uf.w131_trajectory import (
    MAX_SOURCE_SPEED_MS,
    MIN_WALL_DIST_M,
    compute_velocity_orientation,
    enforce_room_constraints,
    generate_source_trajectory,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def room_bbox():
    return AABB(
        min_corner=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        max_corner=np.array([6.0, 3.0, 5.0], dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# UF-W131-01: generate_source_trajectory tests
# ---------------------------------------------------------------------------

class TestStaticTrajectory:
    def test_static_inside_room(self, room_bbox):
        """All positions must equal the fixed position and lie inside room bbox."""
        position = np.array([3.0, 1.5, 2.5], dtype=np.float64)
        traj = generate_source_trajectory(
            "static", room_bbox, duration_s=1.0, seed=42, position=position
        )
        for ts in traj.ticks:
            assert np.allclose(ts.position, position, atol=1e-9), (
                f"Position at tick {ts.tick_id}: {ts.position} != {position}"
            )
            assert room_bbox.contains(ts.position, margin=MIN_WALL_DIST_M), (
                f"Position {ts.position} outside room margin at tick {ts.tick_id}"
            )

    def test_static_random_position_inside_room(self, room_bbox):
        """Static with no position kwarg should still produce positions inside room."""
        traj = generate_source_trajectory("static", room_bbox, duration_s=0.5, seed=7)
        for ts in traj.ticks:
            assert room_bbox.contains(ts.position, margin=MIN_WALL_DIST_M)

    def test_static_all_positions_identical(self, room_bbox):
        """All ticks of a static trajectory should have identical positions."""
        traj = generate_source_trajectory("static", room_bbox, duration_s=1.0, seed=42)
        positions = np.array([ts.position for ts in traj.ticks])
        assert np.allclose(positions, positions[0], atol=1e-12), (
            "Static trajectory has varying positions"
        )


class TestLinearTrajectory:
    def test_linear_trajectory_length(self, room_bbox):
        """n_ticks = round(duration_s * tick_rate_hz) + 1."""
        duration_s = 2.0
        tick_rate_hz = 50.0
        expected_ticks = round(duration_s * tick_rate_hz) + 1  # 101
        traj = generate_source_trajectory(
            "linear", room_bbox, duration_s, tick_rate_hz=tick_rate_hz, seed=42
        )
        assert len(traj.ticks) == expected_ticks, (
            f"Expected {expected_ticks} ticks, got {len(traj.ticks)}"
        )

    def test_linear_trajectory_length_varied_rate(self, room_bbox):
        """Test with non-default tick rate."""
        duration_s = 3.0
        tick_rate_hz = 100.0
        expected_ticks = round(duration_s * tick_rate_hz) + 1  # 301
        traj = generate_source_trajectory(
            "linear", room_bbox, duration_s, tick_rate_hz=tick_rate_hz, seed=42
        )
        assert len(traj.ticks) == expected_ticks

    def test_linear_endpoints_match(self, room_bbox):
        """First tick ≈ start, last tick ≈ end for linear trajectory."""
        start = np.array([1.0, 1.0, 1.0], dtype=np.float64)
        end = np.array([5.0, 2.0, 4.0], dtype=np.float64)
        traj = generate_source_trajectory(
            "linear", room_bbox, 2.0, seed=42, start=start, end=end
        )
        assert np.allclose(traj.ticks[0].position, start, atol=1e-9)
        assert np.allclose(traj.ticks[-1].position, end, atol=1e-9)

    def test_linear_timestamps(self, room_bbox):
        """Timestamps should be evenly spaced at 1/tick_rate_hz intervals."""
        tick_rate_hz = 50.0
        traj = generate_source_trajectory("linear", room_bbox, 1.0, tick_rate_hz=tick_rate_hz, seed=42)
        dt = 1.0 / tick_rate_hz
        for i, ts in enumerate(traj.ticks):
            expected_t = i * dt
            assert abs(ts.timestamp_s - expected_t) < 1e-10, (
                f"Tick {i}: timestamp={ts.timestamp_s:.6f} != {expected_t:.6f}"
            )


class TestRandomWalkTrajectory:
    def test_random_walk_bounds(self, room_bbox):
        """All positions must remain inside room_bbox minus 0.5 m margin."""
        traj = generate_source_trajectory(
            "random_walk", room_bbox, duration_s=5.0, seed=42
        )
        for ts in traj.ticks:
            assert room_bbox.contains(ts.position, margin=MIN_WALL_DIST_M), (
                f"Position {ts.position} outside room margin at tick {ts.tick_id}"
            )

    def test_random_walk_max_speed(self, room_bbox):
        """All velocities must have magnitude ≤ 2.0 m/s (max for random_walk = 1.5)."""
        traj = generate_source_trajectory(
            "random_walk", room_bbox, duration_s=2.0, seed=42
        )
        for ts in traj.ticks:
            speed = float(np.linalg.norm(ts.velocity))
            assert speed <= MAX_SOURCE_SPEED_MS + 1e-6, (
                f"Speed {speed:.4f} m/s exceeds max {MAX_SOURCE_SPEED_MS} at tick {ts.tick_id}"
            )

    def test_random_walk_non_trivial(self, room_bbox):
        """Random walk should actually move (not static) over 5 s."""
        traj = generate_source_trajectory(
            "random_walk", room_bbox, duration_s=5.0, seed=42
        )
        positions = np.array([ts.position for ts in traj.ticks])
        total_displacement = float(np.max(np.linalg.norm(
            positions - positions[0], axis=1
        )))
        assert total_displacement > 0.01, (
            f"Random walk barely moved: total_displacement={total_displacement:.4f} m"
        )


class TestWaypointTrajectory:
    def test_waypoint_interpolation(self, room_bbox):
        """First tick ≈ waypoints[0], last tick ≈ waypoints[-1]."""
        waypoints = np.array([
            [1.0, 1.0, 1.0],
            [3.0, 1.0, 2.5],
            [5.0, 1.0, 4.0],
        ], dtype=np.float64)
        traj = generate_source_trajectory(
            "waypoint", room_bbox, 2.0, seed=42, waypoints=waypoints
        )
        assert np.allclose(traj.ticks[0].position, waypoints[0], atol=0.01), (
            f"First tick {traj.ticks[0].position} != waypoint[0] {waypoints[0]}"
        )
        assert np.allclose(traj.ticks[-1].position, waypoints[-1], atol=0.01), (
            f"Last tick {traj.ticks[-1].position} != waypoint[-1] {waypoints[-1]}"
        )

    def test_waypoint_passes_through_midpoint(self, room_bbox):
        """Middle tick should be approximately at the middle waypoint."""
        waypoints = np.array([
            [1.0, 1.0, 1.0],
            [3.0, 1.5, 2.5],
            [5.0, 2.0, 4.0],
        ], dtype=np.float64)
        traj = generate_source_trajectory(
            "waypoint", room_bbox, 2.0, seed=42, waypoints=waypoints
        )
        mid_tick = len(traj.ticks) // 2
        # At midpoint, position should be near waypoints[1]
        mid_pos = traj.ticks[mid_tick].position
        dist_to_mid_wp = float(np.linalg.norm(mid_pos - waypoints[1]))
        # Should be within ~1 m of the middle waypoint
        assert dist_to_mid_wp < 1.5, (
            f"Mid-tick position {mid_pos} too far from middle waypoint {waypoints[1]}: {dist_to_mid_wp:.4f}"
        )

    def test_waypoint_missing_raises(self, room_bbox):
        """Should raise ValueError if 'waypoints' kwarg is missing."""
        with pytest.raises(ValueError, match="waypoints"):
            generate_source_trajectory("waypoint", room_bbox, 1.0, seed=42)


class TestConversationalTrajectory:
    def test_conversational_inside_room(self, room_bbox):
        """All positions must be inside room_bbox minus margin."""
        traj = generate_source_trajectory(
            "conversational", room_bbox, duration_s=5.0, seed=42
        )
        for ts in traj.ticks:
            assert room_bbox.contains(ts.position, margin=MIN_WALL_DIST_M), (
                f"Position {ts.position} outside room margin at tick {ts.tick_id}"
            )

    def test_conversational_piecewise_static(self, room_bbox):
        """Conversational trajectory should have piecewise-constant positions."""
        traj = generate_source_trajectory(
            "conversational", room_bbox, duration_s=5.0, seed=42
        )
        positions = np.array([ts.position for ts in traj.ticks])
        # Piecewise constant: no position differences larger than 3m within a segment
        # But between speakers, there IS a jump. Count unique positions:
        unique_pos = []
        for pos in positions:
            if not any(np.allclose(pos, up, atol=1e-9) for up in unique_pos):
                unique_pos.append(pos)
        # 5 seconds at 50 Hz with alternating speakers (1–4 s per turn) → 2–5 unique positions
        assert len(unique_pos) >= 2, "Conversational trajectory has only one position"


# ---------------------------------------------------------------------------
# UF-W131-02: compute_velocity_orientation tests
# ---------------------------------------------------------------------------

class TestComputeVelocityOrientation:
    def test_velocity_clamp(self):
        """Velocity > 2.0 m/s should be clamped and a warning issued."""
        positions = np.zeros((3, 3), dtype=np.float64)
        positions[1] = np.array([10.0, 0.0, 0.0])  # 10 m jump at 50 Hz → 500 m/s

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            velocities, _ = compute_velocity_orientation(positions, tick_rate_hz=50.0)

        assert len(caught) > 0, "Expected UserWarning for velocity exceeding max"
        assert any(issubclass(w.category, UserWarning) for w in caught)

        speeds = np.linalg.norm(velocities, axis=1)
        assert np.all(speeds <= MAX_SOURCE_SPEED_MS + 1e-9), (
            f"Speeds not clamped: max={speeds.max():.4f} m/s"
        )

    def test_velocity_finite_difference(self):
        """Velocity[i] = (pos[i+1] - pos[i]) * tick_rate_hz."""
        positions = np.array([
            [0.0, 0.0, 0.0],
            [0.02, 0.0, 0.0],  # 0.02 m in 0.02s = 1.0 m/s at 50 Hz
        ], dtype=np.float64)
        velocities, _ = compute_velocity_orientation(positions, tick_rate_hz=50.0)
        expected_vx = 0.02 * 50.0  # 1.0 m/s
        assert abs(velocities[0, 0] - expected_vx) < 1e-9

    def test_orientation_atan2(self):
        """Yaw orientation = atan2(vx, vz)."""
        positions = np.array([
            [0.0, 0.0, 0.0],
            [0.01, 0.0, 0.01],  # equal x and z → atan2(vx, vz) = π/4
        ], dtype=np.float64)
        velocities, orientations = compute_velocity_orientation(positions, tick_rate_hz=50.0)
        expected_yaw = math.atan2(velocities[0, 0], velocities[0, 2])
        assert abs(orientations[0] - expected_yaw) < 1e-9

    def test_last_velocity_repeated(self):
        """Last velocity should equal second-to-last."""
        positions = np.random.randn(10, 3) * 0.01
        velocities, _ = compute_velocity_orientation(positions, tick_rate_hz=50.0)
        assert np.allclose(velocities[-1], velocities[-2], atol=1e-12)


# ---------------------------------------------------------------------------
# UF-W131-03: enforce_room_constraints tests
# ---------------------------------------------------------------------------

class TestEnforceRoomConstraints:
    def test_clamp_within_margin(self, room_bbox):
        """Positions outside bbox-margin should be clamped."""
        positions = np.array([
            [-1.0, 1.5, 2.5],  # x too small
            [7.0, 1.5, 2.5],   # x too large
            [3.0, -0.5, 2.5],  # y too small
        ], dtype=np.float64)
        constrained = enforce_room_constraints(positions, room_bbox, MIN_WALL_DIST_M)
        lo = room_bbox.min_corner + MIN_WALL_DIST_M
        hi = room_bbox.max_corner - MIN_WALL_DIST_M
        assert np.all(constrained >= lo - 1e-9)
        assert np.all(constrained <= hi + 1e-9)

    def test_valid_positions_unchanged(self, room_bbox):
        """Positions already inside margin should not be modified."""
        lo = room_bbox.min_corner + MIN_WALL_DIST_M
        hi = room_bbox.max_corner - MIN_WALL_DIST_M
        positions = np.array([
            [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
        ], dtype=np.float64)
        constrained = enforce_room_constraints(positions, room_bbox, MIN_WALL_DIST_M)
        assert np.allclose(constrained, positions, atol=1e-12)


# ---------------------------------------------------------------------------
# Reproducibility tests
# ---------------------------------------------------------------------------

class TestReproducibility:
    @pytest.mark.parametrize("motion_type", ["static", "linear", "random_walk", "conversational"])
    def test_reproducibility(self, room_bbox, motion_type):
        """Same seed should produce identical trajectories."""
        traj1 = generate_source_trajectory(motion_type, room_bbox, 2.0, seed=42)
        traj2 = generate_source_trajectory(motion_type, room_bbox, 2.0, seed=42)

        assert len(traj1.ticks) == len(traj2.ticks)
        for ts1, ts2 in zip(traj1.ticks, traj2.ticks):
            assert np.allclose(ts1.position, ts2.position, atol=1e-15), (
                f"{motion_type} tick {ts1.tick_id}: "
                f"position differs between seeds: {ts1.position} vs {ts2.position}"
            )

    def test_different_seeds_differ(self, room_bbox):
        """Different seeds should produce different random_walk trajectories."""
        traj1 = generate_source_trajectory("random_walk", room_bbox, 2.0, seed=42)
        traj2 = generate_source_trajectory("random_walk", room_bbox, 2.0, seed=99)
        positions1 = np.array([ts.position for ts in traj1.ticks])
        positions2 = np.array([ts.position for ts in traj2.ticks])
        # At least one position should differ
        assert not np.allclose(positions1, positions2, atol=1e-9)


# ---------------------------------------------------------------------------
# Unknown motion type test
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_unknown_motion_type_raises(self, room_bbox):
        """Unknown motion_type should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown motion_type"):
            generate_source_trajectory("flying", room_bbox, 1.0, seed=42)

    def test_single_tick_duration(self, room_bbox):
        """Duration so short that n_ticks = 1 should still work."""
        # duration_s = 0 → n_ticks = 1
        traj = generate_source_trajectory("static", room_bbox, duration_s=0.0, seed=42)
        assert len(traj.ticks) == 1

    def test_tick_ids_sequential(self, room_bbox):
        """tick_id should match array index."""
        traj = generate_source_trajectory("linear", room_bbox, 1.0, seed=42)
        for i, ts in enumerate(traj.ticks):
            assert ts.tick_id == i
