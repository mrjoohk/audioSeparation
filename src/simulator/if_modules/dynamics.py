"""
IF-W131..W134: Dynamic Motion Simulation — Integration Module
Composes trajectory generation, synchronization, and dynamic rendering UFs.
"""
from __future__ import annotations

import sys
import os
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from simulator.types import (
    AABB, MaterialMap, ObstacleLayout, RoomGeometry,
    SceneConfig, SceneState, SourceTrajectory, ReceiverTrajectory,
)
from simulator.uf.w131_trajectory import generate_source_trajectory
from simulator.uf.w132_receiver_trajectory import generate_receiver_trajectory
from simulator.uf.w133_sync import (
    synchronize_scene_ticks, create_event_timeline, validate_temporal_alignment,
)
from simulator.uf.w134_dynamic_render import render_dynamic_scene
from simulator.uf.w151_config import derive_subsystem_seeds


class DynamicSceneOrchestrator:
    """Generates trajectories, synchronizes scene ticks, and renders dynamic audio.

    Data flow:
        config → trajectories (W131/W132) → scene states (W133) → rendered audio (W134)
    """

    def __init__(self, config: SceneConfig, room_bbox: AABB) -> None:
        self.config = config
        self.room_bbox = room_bbox
        self._seeds = derive_subsystem_seeds(
            config.seed,
            ["trajectory_src", "trajectory_rec", "noise", "codec"],
        )

    # ------------------------------------------------------------------
    # Trajectory generation
    # ------------------------------------------------------------------

    def generate_trajectories(
        self,
    ) -> Tuple[List[SourceTrajectory], List[ReceiverTrajectory]]:
        """Generate trajectories for all sources and receivers.

        Seeds are derived from the global scene seed per subsystem.

        Returns:
            (src_trajectories, rec_trajectories)
        """
        motion_cfg = self.config.motion or {}
        tick_rate = float(motion_cfg.get("tick_rate_hz", 50.0))

        # Compute duration from motion config or default 10 s
        duration_s = float(motion_cfg.get("duration_s", 10.0))

        src_seed_base = self._seeds["trajectory_src"]
        src_trajectories: List[SourceTrajectory] = []
        for i, src_cfg in enumerate(self.config.sources):
            motion = src_cfg.get("motion", {"type": "static"})
            motion_type = motion.get("type", "static")
            kwargs = {k: v for k, v in motion.items() if k != "type"}
            traj = generate_source_trajectory(
                motion_type=motion_type,
                room_bbox=self.room_bbox,
                duration_s=duration_s,
                tick_rate_hz=tick_rate,
                seed=(src_seed_base + i) & 0x7FFFFFFF,
                **kwargs,
            )
            src_trajectories.append(traj)

        rec_seed_base = self._seeds["trajectory_rec"]
        rec_trajectories: List[ReceiverTrajectory] = []
        for i, rec_cfg in enumerate(self.config.receivers):
            motion = rec_cfg.get("motion", {"type": "static"})
            receiver_type = motion.get("type", "static")
            kwargs = {k: v for k, v in motion.items() if k != "type"}
            traj = generate_receiver_trajectory(
                receiver_type=receiver_type,
                room_bbox=self.room_bbox,
                duration_s=duration_s,
                tick_rate_hz=tick_rate,
                seed=(rec_seed_base + i) & 0x7FFFFFFF,
                **kwargs,
            )
            rec_trajectories.append(traj)

        return src_trajectories, rec_trajectories

    # ------------------------------------------------------------------
    # Scene synchronization
    # ------------------------------------------------------------------

    def synchronize(
        self,
        src_trajectories: List[SourceTrajectory],
        rec_trajectories: List[ReceiverTrajectory],
        room: RoomGeometry,
        obstacles: ObstacleLayout,
        material_map: Optional[MaterialMap] = None,
    ) -> List[SceneState]:
        """Build tick-aligned SceneState sequence.

        Args:
            src_trajectories: Source trajectory list.
            rec_trajectories: Receiver trajectory list.
            room: Built room geometry.
            obstacles: Placed obstacle layout.
            material_map: Optional material map for scene states.

        Returns:
            List[SceneState], one per tick.
        """
        motion_cfg = self.config.motion or {}
        tick_rate = float(motion_cfg.get("tick_rate_hz", 50.0))
        return synchronize_scene_ticks(
            src_trajectories=src_trajectories,
            rec_trajectories=rec_trajectories,
            room=room,
            obstacles=obstacles,
            tick_rate_hz=tick_rate,
        )

    # ------------------------------------------------------------------
    # Event timeline
    # ------------------------------------------------------------------

    def create_event_timeline(
        self,
        src_trajectories: List[SourceTrajectory],
        speech_events: Optional[Dict[str, Dict]] = None,
    ) -> dict:
        """Build tick-aligned speech event timeline.

        Args:
            src_trajectories: Source trajectory list (provides tick count).
            speech_events: Optional {source_id: {start_s, end_s}}.

        Returns:
            {source_id: {active_ticks, start_tick, end_tick}}
        """
        motion_cfg = self.config.motion or {}
        tick_rate = float(motion_cfg.get("tick_rate_hz", 50.0))

        if not src_trajectories:
            return {}

        total_ticks = min(len(t.ticks) for t in src_trajectories)
        source_ids = [t.source_id for t in src_trajectories]

        # Default: all sources active for full duration
        if speech_events is None:
            speech_events = {
                sid: {"start_s": 0.0, "end_s": total_ticks / tick_rate}
                for sid in source_ids
            }

        start_times = [speech_events.get(sid, {}).get("start_s", 0.0) for sid in source_ids]
        end_times = [
            speech_events.get(sid, {}).get("end_s", total_ticks / tick_rate)
            for sid in source_ids
        ]

        return create_event_timeline(
            source_ids=source_ids,
            speech_start_times=start_times,
            speech_end_times=end_times,
            total_ticks=total_ticks,
            tick_rate_hz=tick_rate,
        )

    # ------------------------------------------------------------------
    # Dynamic rendering
    # ------------------------------------------------------------------

    def render_dynamic(
        self,
        scene_states: List[SceneState],
        source_signals: Dict[str, np.ndarray],
        fs: Optional[int] = None,
    ) -> Dict[str, np.ndarray]:
        """Render time-varying audio using OLA convolution.

        Args:
            scene_states: Tick-aligned SceneState list.
            source_signals: Dry audio {source_id: float32[N]}.
            fs: Sample rate (defaults to config.sample_rate).

        Returns:
            {receiver_id: float32[N_out]}
        """
        if fs is None:
            fs = self.config.sample_rate

        result = render_dynamic_scene(
            scene_states=scene_states,
            source_signals=source_signals,
            fs=fs,
        )
        return result.get("rendered_signals", {})


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def run_dynamic_simulation(
    config: SceneConfig,
    room: RoomGeometry,
    obstacles: ObstacleLayout,
    material_map: MaterialMap,
    source_signals: Dict[str, np.ndarray],
) -> dict:
    """Run full dynamic simulation: trajectories → sync → render.

    Args:
        config: Validated SceneConfig.
        room: Built room geometry.
        obstacles: Placed obstacle layout.
        material_map: Surface material map.
        source_signals: Dry audio per source {source_id: float32[N]}.

    Returns:
        dict with keys: rendered_signals, src_trajectories, rec_trajectories,
                        scene_states, event_timeline
    """
    from simulator.uf.w111_room_geometry import generate_bounding_volume
    bbox = generate_bounding_volume(room)

    orchestrator = DynamicSceneOrchestrator(config, bbox)
    src_traj, rec_traj = orchestrator.generate_trajectories()
    scene_states = orchestrator.synchronize(src_traj, rec_traj, room, obstacles, material_map)
    event_timeline = orchestrator.create_event_timeline(src_traj)
    rendered = orchestrator.render_dynamic(scene_states, source_signals)

    return {
        "rendered_signals": rendered,
        "src_trajectories": src_traj,
        "rec_trajectories": rec_traj,
        "scene_states": scene_states,
        "event_timeline": event_timeline,
    }
