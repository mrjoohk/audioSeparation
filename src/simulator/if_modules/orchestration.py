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

def simulate_scene(config: SceneConfig) -> dict:
    """Complete simulation pipeline for one scene.

    This function is designed to be called by the batch executor as simulate_fn.
    It executes the full pipeline:
        validate → build scene → generate trajectories → propagate → device chain → export

    Args:
        config: Validated SceneConfig.

    Returns:
        dict with keys: scene_id, output_dir, manifest_path, acoustic_summary,
                        elapsed_s, status
    """
    from simulator.if_modules.scene_world import SceneWorldBuilder
    from simulator.if_modules.propagation import AcousticPropagationEngine
    from simulator.if_modules.dynamics import DynamicSceneOrchestrator
    from simulator.if_modules.capture import CaptureDeviceChain
    from simulator.uf.w111_room_geometry import generate_bounding_volume
    from simulator.uf.w153_metadata import export_scene_parameters

    t0 = time.time()
    scene_id = config.scene_id
    out_dir = os.path.join(config.output_dir, scene_id)
    os.makedirs(out_dir, exist_ok=True)

    # --- 1. Build scene world ---
    builder = SceneWorldBuilder(config, seed=config.seed)
    room = builder.build_room()
    materials = builder.build_materials()
    obstacles = builder.build_obstacles()
    plausibility = builder.validate()

    if not plausibility.passed:
        warnings.warn(f"[{scene_id}] Plausibility check failed: {plausibility.errors}")

    # --- 2. Generate trajectories ---
    bbox = generate_bounding_volume(room)
    dyn = DynamicSceneOrchestrator(config, bbox)
    src_traj, rec_traj = dyn.generate_trajectories()

    # --- 3. Synchronize scene states ---
    scene_states = dyn.synchronize(src_traj, rec_traj, room, obstacles, materials)
    if not scene_states:
        raise RuntimeError(f"[{scene_id}] No scene states generated")

    # --- 4. Generate stub dry source signals (white noise for testing) ---
    fs = config.sample_rate
    duration_s = float((config.motion or {}).get("duration_s", 5.0))
    n_samples = int(duration_s * fs)
    rng = np.random.default_rng(config.seed)
    source_signals: Dict[str, np.ndarray] = {
        src["source_id"]: (rng.standard_normal(n_samples) * 0.01).astype(np.float32)
        for src in config.sources
    }

    # --- 5. Acoustic propagation (first tick for metadata) ---
    engine = AcousticPropagationEngine(fs=fs, ism_order=config.ism_order)
    first_state = scene_states[0]
    rirs = engine.generate_all_rirs(first_state)
    rendered = engine.render_scene(first_state, source_signals)

    # --- 6. Device chain ---
    chain = CaptureDeviceChain(config, seed=config.seed)
    C = len(config.receivers)
    # Build minimal MicSpec list (flat response, omni pattern)
    mic_specs = [
        MicSpec(
            mic_id=rec["receiver_id"],
            freq_response_db=np.zeros(2),
            freq_bins_hz=np.array([100.0, fs / 2]),
            pattern_type="omni",
        )
        for rec in config.receivers
    ]
    # Stack rendered signals into [C×N]
    rec_ids = [rec["receiver_id"] for rec in config.receivers]
    n_out = max((len(v) for v in rendered.values()), default=n_samples)
    raw_matrix = np.zeros((C, n_out), dtype=np.float32)
    for i, rid in enumerate(rec_ids):
        if rid in rendered:
            sig = rendered[rid]
            raw_matrix[i, :len(sig)] = sig

    processed, chain_meta = chain.process_full_chain(raw_matrix, mic_specs)

    # --- 7. Export audio WAV files ---
    import struct, wave

    audio_files: List[str] = []
    for i, rid in enumerate(rec_ids):
        wav_path = os.path.join(out_dir, f"receiver_{rid}.wav")
        _write_wav(processed[i], wav_path, fs)
        audio_files.append(wav_path)

    # Export clean source references
    for src_id, sig in source_signals.items():
        wav_path = os.path.join(out_dir, f"source_{src_id}_clean.wav")
        _write_wav(sig, wav_path, fs)

    # --- 8. Export RIR files ---
    rir_files: List[str] = []
    for (src_id, rec_id), rir in rirs.items():
        rir_path = os.path.join(out_dir, f"rir_{src_id}_{rec_id}.wav")
        _write_wav(rir.h, rir_path, fs)
        rir_files.append(rir_path)

    # --- 9. Acoustic summary ---
    first_rir = next(iter(rirs.values())) if rirs else None
    rt60 = first_rir.rt60_measured_s if first_rir else plausibility.predicted_rt60_s
    drr = first_rir.drr_db if first_rir else plausibility.predicted_drr_db

    acoustic_summary = AcousticSummary(
        scene_id=scene_id,
        rt60_measured_s=rt60,
        drr_db=drr,
        snr_db=float(np.mean(chain_meta.get("snr_per_channel_db", [0.0]))),
        doa_az_deg=None,
        doa_el_deg=None,
        sabine_rt60_s=plausibility.predicted_rt60_s,
    )

    # --- 10. Export metadata and manifest ---
    export_scene_parameters(config, os.path.join(out_dir, "params.json"))
    manifest = write_scene_manifest(
        scene_id=scene_id,
        output_dir=config.output_dir,
        audio_files=audio_files,
        rir_files=rir_files,
        metadata_json_path=os.path.join(out_dir, "params.json"),
        acoustic_summary=acoustic_summary,
    )

    elapsed = time.time() - t0
    return {
        "scene_id": scene_id,
        "output_dir": out_dir,
        "manifest_path": os.path.join(out_dir, "scene_manifest.json"),
        "acoustic_summary": acoustic_summary,
        "elapsed_s": elapsed,
        "status": "completed",
    }


def _write_wav(signal: np.ndarray, path: str, fs: int) -> None:
    """Write float32 signal to 32-bit float WAV."""
    import wave, struct
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sig = signal.astype(np.float32)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(4)   # 32-bit
        wf.setframerate(fs)
        # wave module writes int PCM; use raw bytes for float32
        wf.writeframes(sig.tobytes())
