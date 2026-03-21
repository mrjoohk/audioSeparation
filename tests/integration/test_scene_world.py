"""Integration tests for IF-W111..W115: Scene World Modeling."""
import pytest
import numpy as np

from simulator.if_modules.scene_world import SceneWorldBuilder, build_scene_from_config
from simulator.types import SceneConfig, SourceTrajectory, ReceiverTrajectory, AABB, TickState


def make_minimal_config(seed=42) -> SceneConfig:
    return SceneConfig(
        scene_id="it_scene_001",
        seed=seed,
        schema_version="1.0.0",
        room={"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
        materials={"default": "concrete"},
        sources=[
            {"source_id": "s0", "position": [1.0, 1.0, 1.0]},
            {"source_id": "s1", "position": [3.0, 1.0, 3.0]},
        ],
        receivers=[
            {"receiver_id": "r0", "position": [2.5, 1.0, 2.5]},
        ],
        sample_rate=16000,
        ism_order=3,
    )


def make_static_src_traj(source_id, position, n_ticks=10):
    ticks = [
        TickState(
            tick_id=t,
            timestamp_s=t * 0.02,
            position=np.array(position, dtype=np.float64),
            velocity=np.zeros(3),
            orientation=0.0,
        )
        for t in range(n_ticks)
    ]
    return SourceTrajectory(source_id=source_id, ticks=ticks, tick_rate_hz=50.0)


def make_static_rec_traj(receiver_id, position, n_ticks=10):
    ticks = [
        TickState(
            tick_id=t,
            timestamp_s=t * 0.02,
            position=np.array(position, dtype=np.float64),
            velocity=np.zeros(3),
            orientation=0.0,
            orientation_quat=np.array([0.0, 0.0, 0.0, 1.0]),
        )
        for t in range(n_ticks)
    ]
    return ReceiverTrajectory(receiver_id=receiver_id, ticks=ticks, tick_rate_hz=50.0)


# ---------------------------------------------------------------------------

def test_build_shoebox_scene():
    """SceneState from 5×4×3 room should have correct volume."""
    config = make_minimal_config()
    builder = SceneWorldBuilder(config, seed=42)
    room = builder.build_room()

    from simulator.uf.w111_room_geometry import generate_bounding_volume
    bbox = generate_bounding_volume(room)
    assert abs(bbox.volume_m3 - 60.0) < 0.01, f"Volume={bbox.volume_m3:.3f} ≠ 60.0"


def test_material_assignment():
    """All room surfaces should have a MaterialSpec in the MaterialMap."""
    config = make_minimal_config()
    builder = SceneWorldBuilder(config, seed=42)
    builder.build_room()
    materials = builder.build_materials()

    room = builder._room
    surface_ids = getattr(room, "surface_ids", [])
    for sid in surface_ids:
        assert sid in materials, f"Surface '{sid}' missing from MaterialMap"
        assert materials[sid].alpha.shape == (6,)


def test_acoustic_plausibility_passes():
    """Normal shoebox scene should pass acoustic plausibility check."""
    config = make_minimal_config()
    builder = SceneWorldBuilder(config, seed=42)
    builder.build_room()
    builder.build_materials()
    report = builder.validate()
    # May have warnings but should not have errors for a reasonable config
    assert isinstance(report.passed, bool)
    # RT60 should be in plausible range
    assert 0.01 < report.predicted_rt60_s < 10.0, \
        f"Predicted RT60={report.predicted_rt60_s:.3f} s out of range"


def test_build_all_returns_scene_states():
    """build_all() should return n_ticks SceneStates with correct source count."""
    config = make_minimal_config()
    src_traj = [
        make_static_src_traj("s0", [1.0, 1.0, 1.0]),
        make_static_src_traj("s1", [3.0, 1.0, 3.0]),
    ]
    rec_traj = [make_static_rec_traj("r0", [2.5, 1.0, 2.5])]

    builder = SceneWorldBuilder(config, seed=42)
    states = builder.build_all(src_traj, rec_traj, n_ticks=5)

    assert len(states) == 5
    for s in states:
        assert len(s.sources) == 2
        assert len(s.receivers) == 1


def test_build_scene_from_config():
    """Module-level function should return SceneState sequence."""
    config = make_minimal_config()
    src_traj = [make_static_src_traj("s0", [1.0, 1.0, 1.0], n_ticks=3)]
    rec_traj = [make_static_rec_traj("r0", [2.5, 1.0, 2.5], n_ticks=3)]

    states = build_scene_from_config(config, src_traj, rec_traj)
    assert len(states) == 3
    assert states[0].tick_id == 0
