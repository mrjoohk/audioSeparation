"""
W100000 Spatial Simulator — Top-Level Facade
Single entry point for end-to-end scene simulation and batch generation.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulator.types import ExecutionSummary, SceneConfig
from simulator.uf.w151_config import SceneConfigValidator, load_config_from_file
from simulator.if_modules.orchestration import SimulatorOrchestrator, simulate_scene


class Simulator:
    """W100000 Spatial Simulator facade.

    Example::

        sim = Simulator("scene_config.yaml", output_dir="output/")
        result = sim.run_single()
        print(result["acoustic_summary"].rt60_measured_s)
    """

    def __init__(self, config_path: str, output_dir: str = "output") -> None:
        self.config_path = str(config_path)
        self.output_dir = str(output_dir)
        self._orchestrator = SimulatorOrchestrator(config_path, output_dir)
        self._config: SceneConfig | None = None

    def _ensure_config(self) -> SceneConfig:
        if self._config is None:
            self._config = self._orchestrator.load_and_validate_config()
        return self._config

    def run_single(self) -> dict:
        """Run one scene end-to-end and return results dict.

        Returns:
            dict with keys: scene_id, output_dir, manifest_path,
                            acoustic_summary, elapsed_s, status
        """
        config = self._ensure_config()
        return simulate_scene(config)

    def run_batch(self, n_workers: int = 4) -> ExecutionSummary:
        """Run batch simulation using all configs in a directory or config list.

        For a single config this creates one job. Extend by passing a list of
        configs to SimulatorOrchestrator.run_batch() directly.

        Args:
            n_workers: Number of parallel worker processes.

        Returns:
            ExecutionSummary with throughput statistics.
        """
        config = self._ensure_config()
        return self._orchestrator.run_batch(
            configs=[config],
            simulate_fn=simulate_scene,
            worker_count=n_workers,
        )

    def visualize(self, scene_id: str | None = None) -> None:
        """Generate diagnostic plots for a completed scene.

        Args:
            scene_id: Scene ID to visualize. Defaults to config.scene_id.
        """
        from simulator.uf.w154_visualization import (
            plot_room_layout, plot_rir_statistics,
        )
        from simulator.if_modules.scene_world import SceneWorldBuilder
        from simulator.uf.w111_room_geometry import generate_bounding_volume

        config = self._ensure_config()
        sid = scene_id or config.scene_id
        out_dir = os.path.join(self.output_dir, sid, "viz")
        os.makedirs(out_dir, exist_ok=True)

        builder = SceneWorldBuilder(config, seed=config.seed)
        room = builder.build_room()
        bbox = generate_bounding_volume(room)

        import numpy as np
        src_positions = [
            np.array(s.get("position", [1.0, 1.0, 1.0]))
            for s in config.sources
        ]
        rec_positions = [
            np.array(r.get("position", [2.0, 1.0, 2.0]))
            for r in config.receivers
        ]

        plot_room_layout(
            room_bbox=bbox,
            sources=src_positions,
            receivers=rec_positions,
            output_path=os.path.join(out_dir, "room_layout.png"),
        )
        print(f"Visualization saved to {out_dir}/")
