"""
IF-W111..W115: Scene World Modeling — Integration Module
Composes UF-level geometry, material, obstacle, transform, and scene-state functions
into a single SceneWorldBuilder API.
"""
from __future__ import annotations

import sys
import os
import warnings
from typing import List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from simulator.types import (
    AABB, MaterialMap, ObstacleLayout, PlacedObject, PlausibilityReport,
    RoomGeometry, SceneConfig, SceneState, SourceTrajectory, ReceiverTrajectory,
    WorldFrame,
)
from simulator.uf.w111_room_geometry import (
    define_room_primitive, generate_bounding_volume, validate_manifold,
)
from simulator.uf.w112_material import (
    MaterialDB, assign_materials, stochastic_material_variation,
)
from simulator.uf.w113_obstacle import (
    place_obstacle_objects, tag_acoustic_roles, check_collisions,
)
from simulator.uf.w114_transforms import define_world_frame
from simulator.uf.w115_scene_state import assemble_scene_state
from simulator.uf.w155_validation import validate_acoustic_plausibility


class SceneWorldBuilder:
    """Builds and validates the complete acoustic scene world from a SceneConfig.

    Data flow:
        build_room() → build_materials() → build_obstacles() → build_world_frame()
        → validate() → build_scene_state() per tick
    """

    def __init__(self, config: SceneConfig, seed: int = 42) -> None:
        self.config = config
        self.seed = seed
        self._db = MaterialDB()
        self._room: Optional[RoomGeometry] = None
        self._bbox: Optional[AABB] = None
        self._materials: Optional[MaterialMap] = None
        self._obstacles: Optional[ObstacleLayout] = None
        self._world_frame: Optional[WorldFrame] = None

    # ------------------------------------------------------------------
    # Stage builders
    # ------------------------------------------------------------------

    def build_room(self) -> RoomGeometry:
        """Instantiate room geometry from config."""
        room_cfg = self.config.room
        room_type = room_cfg.get("type", "shoebox")
        params = room_cfg.get("dimensions", {"L": 5.0, "W": 4.0, "H": 3.0})

        if room_type in ("shoebox", "corridor", "hall"):
            self._room = define_room_primitive(room_type, params)
        else:
            raise ValueError(f"Unsupported room type '{room_type}'. "
                             f"Mesh import not supported via config string; pass MeshRoom directly.")

        self._bbox = generate_bounding_volume(self._room)
        return self._room

    def build_materials(self) -> MaterialMap:
        """Assign frequency-dependent materials to room surfaces."""
        if self._room is None:
            self.build_room()

        mat_cfg = self.config.materials or {}
        surface_ids: List[str] = getattr(self._room, "surface_ids", [])

        # Build assignment map from config; default all surfaces to "concrete"
        assignments = {sid: mat_cfg.get(sid, mat_cfg.get("default", "concrete"))
                       for sid in surface_ids}

        self._materials = assign_materials(surface_ids, assignments, self._db)

        # Apply stochastic variation if requested
        if mat_cfg.get("stochastic_variation", False):
            sigma = float(mat_cfg.get("variation_sigma", 0.05))
            subseed = (self.seed * 31 + 1) & 0x7FFFFFFF
            self._materials = {
                sid: stochastic_material_variation(spec, sigma, subseed + i)
                for i, (sid, spec) in enumerate(self._materials.items())
            }

        return self._materials

    def build_obstacles(self) -> ObstacleLayout:
        """Place and tag obstacle objects inside the room."""
        if self._bbox is None:
            self.build_room()

        obstacle_cfg = self.config.room.get("obstacles", [])
        from simulator.types import ObjectSpec
        import numpy as np

        specs = []
        for o in obstacle_cfg:
            pos_raw = o.get("position")
            specs.append(ObjectSpec(
                object_type=o.get("type", "table"),
                size=np.array(o.get("size", [0.8, 0.75, 0.8]), dtype=np.float64),
                acoustic_role=o.get("acoustic_role", "reflective"),
                position=np.array(pos_raw, dtype=np.float64) if pos_raw is not None else None,
                rotation_y=float(o.get("rotation_y", 0.0)),
            ))

        subseed = (self.seed * 31 + 2) & 0x7FFFFFFF
        layout = place_obstacle_objects(self._bbox, specs, subseed)
        layout = tag_acoustic_roles(layout)

        collision_report = check_collisions(layout, self._bbox)
        if collision_report["n_violations"] > 0:
            warnings.warn(
                f"SceneWorldBuilder: {collision_report['n_violations']} obstacle collision(s) "
                f"detected: {collision_report['violating_pairs']}"
            )

        self._obstacles = layout
        return self._obstacles

    def build_world_frame(self) -> WorldFrame:
        """Establish the global world coordinate frame."""
        convention = self.config.room.get("coordinate_convention", "Y-up-RH")
        import numpy as np
        self._world_frame = define_world_frame(
            origin=np.zeros(3), convention=convention
        )
        return self._world_frame

    def validate(self) -> PlausibilityReport:
        """Run acoustic plausibility checks before rendering."""
        if self._room is None:
            self.build_room()
        if self._materials is None:
            self.build_materials()

        src_cfgs = self.config.sources
        rec_cfgs = self.config.receivers
        report = validate_acoustic_plausibility(
            self._room, self._materials, src_cfgs, rec_cfgs
        )

        if not report.passed:
            warnings.warn(
                f"SceneWorldBuilder: Acoustic plausibility check failed — "
                f"{report.errors}"
            )
        for w in report.warnings:
            warnings.warn(f"SceneWorldBuilder [plausibility]: {w}")

        return report

    def build_scene_state(
        self,
        src_trajectories: List[SourceTrajectory],
        rec_trajectories: List[ReceiverTrajectory],
        tick_id: int = 0,
    ) -> SceneState:
        """Assemble a single-tick SceneState."""
        if self._room is None:
            self.build_room()
        if self._materials is None:
            self.build_materials()
        if self._obstacles is None:
            self.build_obstacles()

        return assemble_scene_state(
            room=self._room,
            material_map=self._materials,
            obstacles=self._obstacles,
            src_trajectories=src_trajectories,
            rec_trajectories=rec_trajectories,
            tick_id=tick_id,
        )

    def build_all(
        self,
        src_trajectories: List[SourceTrajectory],
        rec_trajectories: List[ReceiverTrajectory],
        n_ticks: int = 1,
    ) -> List[SceneState]:
        """End-to-end build: room → materials → obstacles → validate → all ticks.

        Returns:
            List of SceneState, one per tick.
        """
        self.build_room()
        self.build_materials()
        self.build_obstacles()
        self.build_world_frame()
        self.validate()

        return [
            self.build_scene_state(src_trajectories, rec_trajectories, tick_id=t)
            for t in range(n_ticks)
        ]


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def build_scene_from_config(
    config: SceneConfig,
    src_trajectories: List[SourceTrajectory],
    rec_trajectories: List[ReceiverTrajectory],
) -> List[SceneState]:
    """Build a full scene state sequence from a validated SceneConfig.

    Args:
        config: Validated SceneConfig dataclass.
        src_trajectories: One SourceTrajectory per source.
        rec_trajectories: One ReceiverTrajectory per receiver.

    Returns:
        List[SceneState] aligned to the minimum trajectory length.
    """
    builder = SceneWorldBuilder(config, seed=config.seed)

    n_src_ticks = min(len(t.ticks) for t in src_trajectories) if src_trajectories else 1
    n_rec_ticks = min(len(t.ticks) for t in rec_trajectories) if rec_trajectories else 1
    n_ticks = min(n_src_ticks, n_rec_ticks)

    return builder.build_all(src_trajectories, rec_trajectories, n_ticks=n_ticks)
