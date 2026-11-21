"""
IF-W151..W155: Simulator Orchestration & Export — Integration Module
Top-level orchestration: config validation → scene build → propagation
→ device chain → metadata export.
"""
from __future__ import annotations

import sys
import os
import json
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from simulator.types import (
    AcousticSummary, ArrayConfig, ExecutionSummary,
    MicSpec, PlausibilityReport, SceneConfig,
)
from simulator.uf.w151_config import (
    SceneConfigValidator, load_config_from_file, derive_subsystem_seeds,
)
from simulator.uf.w152_batch import run_batch
from simulator.uf.w153_metadata import (
    export_scene_parameters, export_acoustic_summary,
    write_scene_manifest, build_dataset_index,
)
from simulator.uf.w154_visualization import (
    plot_room_layout, plot_rir_statistics,
    plot_waveform_channels, plot_rt60_comparison,
)
from simulator.uf.w155_validation import (
    validate_acoustic_plausibility, validate_config_completeness,
)


class SimulatorOrchestrator:
    """End-to-end simulation orchestrator.

    Coordinates config loading, scene building, propagation, device chain,
    visualization, and metadata export.
    """

    def __init__(
        self,
        config_path_or_dict,
        output_dir: str = "output",
    ) -> None:
        self.output_dir = str(output_dir)
        self._raw_config: dict = (
            config_path_or_dict
            if isinstance(config_path_or_dict, dict)
            else load_config_from_file(str(config_path_or_dict))
        )
        self._config: Optional[SceneConfig] = None

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def load_and_validate_config(self) -> SceneConfig:
        """Validate raw config dict and return typed SceneConfig."""
        validator = SceneConfigValidator()
        self._config = validator.validate(self._raw_config)
        completeness = validate_config_completeness(self._config)
        if not completeness["passed"]:
            warnings.warn(
                f"Config completeness check failed: {completeness['missing_refs']}"
            )
        return self._config

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_scene(self, room, materials, sources, receivers) -> PlausibilityReport:
        """Run acoustic plausibility checks on the built scene."""
        return validate_acoustic_plausibility(room, materials, sources, receivers)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_results(
        self,
        scene_id: str,
        audio_files: List[str],
        rir_files: List[str],
        acoustic_summary: AcousticSummary,
    ) -> dict:
        """Write scene manifest and acoustic summary JSON.

        Returns:
            Manifest dict.
        """
        summary_path = os.path.join(self.output_dir, scene_id, "acoustic_summary.json")
        export_acoustic_summary(acoustic_summary, summary_path)

        return write_scene_manifest(
            scene_id=scene_id,
            output_dir=self.output_dir,
            audio_files=audio_files,
            rir_files=rir_files,
            metadata_json_path=os.path.join(self.output_dir, scene_id, "params.json"),
            acoustic_summary=acoustic_summary,
        )

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------

    def visualize_scene(
        self,
        room_bbox,
        sources,
        receivers,
        rirs,
        output_dir: Optional[str] = None,
    ) -> None:
        """Generate all diagnostic plots for a scene."""
        out = output_dir or os.path.join(self.output_dir, "viz")
        os.makedirs(out, exist_ok=True)

        plot_room_layout(
            room_bbox=room_bbox,
            sources=sources,
            receivers=receivers,
            output_path=os.path.join(out, "room_layout.png"),
        )

        if rirs:
            first_rir = next(iter(rirs.values()))
            plot_rir_statistics(
                rir=first_rir,
                output_path=os.path.join(out, "rir_statistics.png"),
            )

    # ------------------------------------------------------------------
    # Batch execution
    # ------------------------------------------------------------------

    def run_batch(
        self,
        configs: List[SceneConfig],
        simulate_fn,
        worker_count: int = 4,
    ) -> ExecutionSummary:
        """Run batch simulation using multiprocessing.

        Args:
            configs: List of validated SceneConfigs.
            simulate_fn: callable(SceneConfig) → dict
            worker_count: Number of parallel workers.

        Returns:
            ExecutionSummary with throughput statistics.
        """
        checkpoint = os.path.join(self.output_dir, "batch_checkpoint.json")
        return run_batch(
            configs=configs,
            worker_count=worker_count,
            output_dir=self.output_dir,
            simulate_fn=simulate_fn,
            checkpoint_file=checkpoint,
        )


# ---------------------------------------------------------------------------
# Top-level simulate_scene — used as simulate_fn by BatchExecutor
# ---------------------------------------------------------------------------

def simulate_scene(config: SceneConfig, source_signals: Optional[Dict[str, np.ndarray]] = None) -> dict:
    """Complete simulation pipeline for one scene (static_v1 profile).

    Delegates to :func:`simulator.scene_pipeline.simulate_scene`, which renders
    the mixture, per-source references and noise on one time base, runs QC and
    commits the scene directory atomically.  See
    design_md/W100000/W1_audit_remediation_design.md §3–§4.

    Returns:
        dict with keys: scene_id, output_dir, manifest_path, acoustic_summary,
        elapsed_s, status, fingerprint, audio_duration_s, bytes_written, qc
    """
    from simulator.scene_pipeline import simulate_scene as _simulate
    return _simulate(config, source_signals=source_signals)


def _write_wav(signal: np.ndarray, path: str, fs: int) -> None:
    """Write a signal as IEEE-float32 WAV (kept for backward compatibility)."""
    from simulator.scene_io import write_wav_float32
    write_wav_float32(path, signal, fs)
