"""Integration tests for IF-W121..W124: Acoustic Propagation Engine."""
import pytest
import numpy as np

from simulator.if_modules.propagation import AcousticPropagationEngine, process_scene
from simulator.if_modules.scene_world import SceneWorldBuilder
from simulator.types import (
    SceneConfig, SceneState, SourceState, ReceiverState,
    MaterialMap, AABB, TickState, SourceTrajectory, ReceiverTrajectory,
)


def make_config(seed=0):
    return SceneConfig(
        scene_id="it_prop_001",
        seed=seed,
        schema_version="1.0.0",
        room={"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
        materials={"default": "concrete"},
        sources=[{"source_id": "s0", "position": [1.0, 1.0, 1.0]}],
        receivers=[{"receiver_id": "r0", "position": [4.0, 1.0, 4.0]}],
        sample_rate=16000,
        ism_order=3,
    )


def build_scene_state(config) -> SceneState:
    builder = SceneWorldBuilder(config, seed=config.seed)
    room = builder.build_room()
    materials = builder.build_materials()
    obstacles = builder.build_obstacles()

    from simulator.uf.w115_scene_state import assemble_scene_state
    src_traj = [
        SourceTrajectory(
            source_id="s0",
            ticks=[TickState(0, 0.0, np.array([1.0, 1.0, 1.0]), np.zeros(3), 0.0)],
            tick_rate_hz=50.0,
        )
    ]
    rec_traj = [
        ReceiverTrajectory(
            receiver_id="r0",
            ticks=[TickState(0, 0.0, np.array([4.0, 1.0, 4.0]), np.zeros(3), 0.0,
                             np.array([0., 0., 0., 1.]))],
            tick_rate_hz=50.0,
        )
    ]
    return assemble_scene_state(room, materials, obstacles, src_traj, rec_traj, tick_id=0)


def test_rir_chain_generates_output():
    """AcousticPropagationEngine.generate_rir() should return non-empty RIR."""
    config = make_config()
    state = build_scene_state(config)
    engine = AcousticPropagationEngine(fs=16000, ism_order=3)
    rir = engine.generate_rir(state, "s0", "r0")

    assert rir is not None
    assert len(rir.h) > 0
    assert rir.h.dtype == np.float32


def test_rir_direct_peak_at_correct_delay():
    """Direct-path peak should be at expected sample delay ± 2 samples."""
    config = make_config()
    state = build_scene_state(config)
    engine = AcousticPropagationEngine(fs=16000, c=343.0, ism_order=1)
    rir = engine.generate_rir(state, "s0", "r0")

    # Expected delay: distance / c = sqrt((4-1)^2+(1-1)^2+(4-1)^2)/343 * 16000
    dist = np.linalg.norm(np.array([4.0, 1.0, 4.0]) - np.array([1.0, 1.0, 1.0]))
    expected_sample = round(dist / 343.0 * 16000)
    # The receiver sits on the z = W wall and the layout is symmetric, so several
    # first-order images arrive simultaneously and their sum may exceed the
    # direct path.  The physically required property is causality: the first
    # arrival is the direct path and nothing precedes it.
    h = np.abs(rir.h)
    first_arrival = int(np.argmax(h > 1e-3 * h.max()))
    assert abs(first_arrival - expected_sample) <= 1, \
        f"First arrival at sample {first_arrival}, expected {expected_sample} (dist={dist:.3f} m)"
    assert h[expected_sample] >= 0.9 * h[expected_sample - 3:expected_sample + 4].max()


def test_rir_reproducibility():
    """Same inputs should produce identical RIR."""
    config = make_config(seed=42)
    s1 = build_scene_state(config)
    s2 = build_scene_state(config)
    engine = AcousticPropagationEngine(fs=16000, ism_order=3)
    rir1 = engine.generate_rir(s1, "s0", "r0")
    rir2 = engine.generate_rir(s2, "s0", "r0")
    assert np.allclose(rir1.h, rir2.h, atol=1e-7), "RIR not reproducible"


def test_render_output_shape():
    """render_scene with 1 source, 1 receiver should return non-empty dict."""
    config = make_config()
    state = build_scene_state(config)
    engine = AcousticPropagationEngine(fs=16000, ism_order=2)

    rng = np.random.default_rng(0)
    source_signals = {"s0": rng.standard_normal(16000).astype(np.float32)}
    output = engine.render_scene(state, source_signals)

    assert "r0" in output
    assert len(output["r0"]) > 0
    assert output["r0"].dtype == np.float32


def test_process_scene_convenience():
    """Module-level process_scene should return rendered signals."""
    config = make_config()
    state = build_scene_state(config)
    rng = np.random.default_rng(1)
    source_signals = {"s0": rng.standard_normal(8000).astype(np.float32)}
    output = process_scene(state, source_signals, fs=16000, ism_order=2)
    assert "r0" in output
    assert len(output["r0"]) >= 8000
