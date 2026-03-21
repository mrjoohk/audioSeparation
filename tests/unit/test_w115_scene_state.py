"""
Unit tests for UF-W115 Scene State Assembly (w115_scene_state.py).

Covers:
- test_assemble_basic
- test_serialize_roundtrip
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

from simulator.types import (
    MaterialMap,
    ReceiverState,
    ReceiverTrajectory,
    SceneState,
    SourceState,
    SourceTrajectory,
    TickState,
)
from simulator.uf.w111_room_geometry import define_room_primitive
from simulator.uf.w112_material import MaterialDB, assign_materials
from simulator.uf.w115_scene_state import assemble_scene_state, serialize_scene_state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_material_db():
    MaterialDB.reset()
    yield
    MaterialDB.reset()


@pytest.fixture
def simple_room():
    return define_room_primitive("shoebox", {"L": 6.0, "W": 5.0, "H": 3.0})


@pytest.fixture
def simple_material_map(simple_room):
    db = MaterialDB.instance()
    assignments = {sid: "concrete" for sid in simple_room.surface_ids}
    assignments["floor"] = "carpet"
    return assign_materials(simple_room.surface_ids, assignments, db)


@pytest.fixture
def src_trajectory() -> SourceTrajectory:
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
        orientation=0.1,
    )
    return SourceTrajectory(source_id="src_0", ticks=[t0, t1], tick_rate_hz=50.0)


@pytest.fixture
def rec_trajectory() -> ReceiverTrajectory:
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
    return ReceiverTrajectory(receiver_id="rec_0", ticks=[r0, r1], tick_rate_hz=50.0)


# ---------------------------------------------------------------------------
# test_assemble_basic
# ---------------------------------------------------------------------------

class TestAssembleBasic:
    def test_returns_scene_state(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        assert isinstance(state, SceneState)

    def test_tick_id_set_correctly(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        for tick_id in (0, 1):
            state = assemble_scene_state(
                room=simple_room,
                material_map=simple_material_map,
                obstacles=[],
                src_trajectories=[src_trajectory],
                rec_trajectories=[rec_trajectory],
                tick_id=tick_id,
            )
            assert state.tick_id == tick_id

    def test_one_source_one_receiver(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        assert len(state.sources) == 1
        assert len(state.receivers) == 1

    def test_source_id_matches(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        assert state.sources[0].source_id == "src_0"

    def test_receiver_id_matches(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        assert state.receivers[0].receiver_id == "rec_0"

    def test_source_position_at_tick_0(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        assert np.allclose(state.sources[0].position, [2.0, 1.5, 2.0])

    def test_source_position_at_tick_1(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=1,
        )
        assert np.allclose(state.sources[0].position, [2.1, 1.5, 2.0])

    def test_tick_id_beyond_trajectory_warns(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        with pytest.warns(UserWarning, match=r"[Ee]xceeds|[Cc]lamp"):
            state = assemble_scene_state(
                room=simple_room,
                material_map=simple_material_map,
                obstacles=[],
                src_trajectories=[src_trajectory],
                rec_trajectories=[rec_trajectory],
                tick_id=999,
            )
        # Should still return a valid state clamped to the last tick
        assert isinstance(state, SceneState)
        # Position should be clamped to tick 1 (last available)
        assert np.allclose(state.sources[0].position, [2.1, 1.5, 2.0])

    def test_no_sources_warns(self, simple_room, simple_material_map, rec_trajectory):
        with pytest.warns(UserWarning, match=r"[Ss]ource|no source"):
            state = assemble_scene_state(
                room=simple_room,
                material_map=simple_material_map,
                obstacles=[],
                src_trajectories=[],
                rec_trajectories=[rec_trajectory],
                tick_id=0,
            )
        assert len(state.sources) == 0

    def test_receiver_orientation_quat_set(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        quat = state.receivers[0].orientation_quat
        assert quat is not None
        assert quat.shape == (4,)

    def test_materials_preserved_in_state(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        assert isinstance(state.materials, dict)
        assert len(state.materials) > 0

    def test_obstacles_preserved_in_state(self, simple_room, simple_material_map, src_trajectory, rec_trajectory):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        assert state.obstacles == []

    def test_multiple_sources_and_receivers(self, simple_room, simple_material_map):
        """Assemble with 2 sources and 2 receivers."""
        def _make_src_traj(sid, px):
            ts = TickState(
                tick_id=0, timestamp_s=0.0,
                position=np.array([px, 1.5, 2.0], dtype=np.float64),
                velocity=np.zeros(3, dtype=np.float64),
                orientation=0.0,
            )
            return SourceTrajectory(source_id=sid, ticks=[ts], tick_rate_hz=50.0)

        def _make_rec_traj(rid, px):
            ts = TickState(
                tick_id=0, timestamp_s=0.0,
                position=np.array([px, 1.5, 3.0], dtype=np.float64),
                velocity=np.zeros(3, dtype=np.float64),
                orientation=0.0,
                orientation_quat=np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float64),
            )
            return ReceiverTrajectory(receiver_id=rid, ticks=[ts], tick_rate_hz=50.0)

        srcs = [_make_src_traj("src_0", 1.0), _make_src_traj("src_1", 3.0)]
        recs = [_make_rec_traj("rec_0", 4.0), _make_rec_traj("rec_1", 5.0)]

        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=srcs,
            rec_trajectories=recs,
            tick_id=0,
        )
        assert len(state.sources) == 2
        assert len(state.receivers) == 2
        assert {s.source_id for s in state.sources} == {"src_0", "src_1"}
        assert {r.receiver_id for r in state.receivers} == {"rec_0", "rec_1"}


# ---------------------------------------------------------------------------
# test_serialize_roundtrip
# ---------------------------------------------------------------------------

class TestSerializeRoundtrip:
    def test_creates_json_file(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        assert os.path.exists(out)

    def test_json_contains_tick_id(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=1,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        assert loaded["tick_id"] == 1

    def test_json_contains_sources(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        assert "sources" in loaded
        assert len(loaded["sources"]) == 1
        assert loaded["sources"][0]["source_id"] == "src_0"

    def test_json_contains_receivers(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        assert "receivers" in loaded
        assert len(loaded["receivers"]) == 1
        assert loaded["receivers"][0]["receiver_id"] == "rec_0"

    def test_source_position_roundtrip(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        pos = loaded["sources"][0]["position"]
        assert pos == pytest.approx([2.0, 1.5, 2.0])

    def test_receiver_position_roundtrip(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        pos = loaded["receivers"][0]["position"]
        assert pos == pytest.approx([4.0, 1.5, 3.0])

    def test_returned_dict_matches_json(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        returned = serialize_scene_state(state, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        assert returned["tick_id"] == loaded["tick_id"]
        assert returned["sources"][0]["source_id"] == loaded["sources"][0]["source_id"]

    def test_serialize_creates_parent_dirs(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "deep" / "nested" / "state.json")
        serialize_scene_state(state, out)
        assert os.path.exists(out)

    def test_json_is_valid_json(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        """File must be parseable as valid JSON."""
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        with open(out, "r") as fh:
            content = fh.read()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)

    def test_materials_in_json(self, simple_room, simple_material_map, src_trajectory, rec_trajectory, tmp_path):
        state = assemble_scene_state(
            room=simple_room,
            material_map=simple_material_map,
            obstacles=[],
            src_trajectories=[src_trajectory],
            rec_trajectories=[rec_trajectory],
            tick_id=0,
        )
        out = str(tmp_path / "state.json")
        serialize_scene_state(state, out)
        with open(out, "r") as fh:
            loaded = json.load(fh)
        assert "materials" in loaded
        assert isinstance(loaded["materials"], dict)
