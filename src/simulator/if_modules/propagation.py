"""
IF-W121..W124: Acoustic Propagation Engine — Integration Module
Composes direct-path, reflection, occlusion, and RIR/BRIR generation UFs
into a unified AcousticPropagationEngine API.
"""
from __future__ import annotations

import sys
import os
import warnings
import zlib
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from simulator.types import (
    BRIR, DirectPath, OcclusionResult, RIR, ReflectionData,
    SceneState, SourceState, ReceiverState, LateReverbSpec,
    ImageSource, SPEED_OF_SOUND,
)
from simulator.uf.w121_direct_path import build_direct_path
from simulator.uf.w122_reverberation import (
    compute_image_sources, generate_late_reverb_tail,
    fit_rt60, estimate_sabine_rt60,
)
from simulator.uf.w123_occlusion import compute_full_occlusion
from simulator.uf.w124_rir_rendering import (
    generate_static_rir_with_mic, render_waveform,
)


class AcousticPropagationEngine:
    """Computes RIRs and renders multichannel audio for a given scene state.

    Data flow per source-receiver pair:
        SceneState → DirectPath (W121) → ReflectionData (W122)
                   → OcclusionResult (W123) → RIR (W124) → rendered waveform
    """

    def __init__(
        self,
        fs: int = 16000,
        c: float = SPEED_OF_SOUND,
        ism_order: int = 3,
        seed: int = 0,
    ) -> None:
        self.fs = fs
        self.c = c
        self.ism_order = ism_order
        self.seed = int(seed)
        self._rir_cache: Dict[Tuple[str, str, int], RIR] = {}

    def pair_seed(self, src_id: str, rec_id: str) -> int:
        """Deterministic late-reverb seed, distinct per (scene seed, source, receiver)."""
        return zlib.crc32(f"{self.seed}:{src_id}:{rec_id}".encode("utf-8")) & 0x7FFFFFFF

    # ------------------------------------------------------------------
    # Per-pair computations
    # ------------------------------------------------------------------

    def compute_direct_path(
        self, scene_state: SceneState, src_id: str, rec_id: str
    ) -> DirectPath:
        """Compute direct-path propagation for one source-receiver pair."""
        src = self._get_source(scene_state, src_id)
        rec = self._get_receiver(scene_state, rec_id)
        mic_quat = rec.orientation_quat if rec.orientation_quat is not None else None
        return build_direct_path(
            src_id=src_id, mic_id=rec_id,
            src_pos=src.position, mic_pos=rec.position,
            fs=self.fs, c=self.c,
            mic_orientation_quat=mic_quat,
        )

    def compute_reflections(
        self, scene_state: SceneState, src_id: str, rec_id: str
    ) -> ReflectionData:
        """Compute image sources and late reverb tail description."""
        src = self._get_source(scene_state, src_id)
        rec = self._get_receiver(scene_state, rec_id)
        room = scene_state.room

        # Extract room dimensions (shoebox assumed for ISM)
        dims = getattr(room, "dimensions", {"L": 5.0, "W": 4.0, "H": 3.0})

        image_sources = compute_image_sources(
            room_dims=dims,
            src_pos=src.position,
            mic_pos=rec.position,
            ism_order=self.ism_order,
            material_map_or_alpha_per_wall=scene_state.materials,
        )

        # Estimate RT60 from Sabine for late tail
        try:
            rt60_est = estimate_sabine_rt60(dims, scene_state.materials)
        except Exception:
            rt60_est = 0.5  # fallback

        mixing_time_ms = min(50.0, rt60_est * 1000 * 0.08)  # ~8% of RT60

        late_spec = LateReverbSpec(
            rt60_s=rt60_est,
            mixing_time_ms=mixing_time_ms,
            seed=self.pair_seed(src_id, rec_id),
        )
        return ReflectionData(image_sources=image_sources, late_tail_spec=late_spec)

    def compute_occlusion(
        self, scene_state: SceneState, src_id: str, rec_id: str
    ) -> OcclusionResult:
        """Compute occlusion/diffraction for one source-receiver pair."""
        src = self._get_source(scene_state, src_id)
        rec = self._get_receiver(scene_state, rec_id)
        return compute_full_occlusion(
            src_id=src_id,
            rec_id=rec_id,
            src_pos=src.position,
            mic_pos=rec.position,
            obstacles=scene_state.obstacles,
        )

    def generate_rir(
        self, scene_state: SceneState, src_id: str, rec_id: str
    ) -> RIR:
        """Generate full RIR for one source-receiver pair.

        Composes: DirectPath → ReflectionData → OcclusionResult → RIR.
        """
        cache_key = (src_id, rec_id, scene_state.tick_id)
        if cache_key in self._rir_cache:
            return self._rir_cache[cache_key]

        direct = self.compute_direct_path(scene_state, src_id, rec_id)
        reflections = self.compute_reflections(scene_state, src_id, rec_id)
        occlusion = self.compute_occlusion(scene_state, src_id, rec_id)

        rec = self._get_receiver(scene_state, rec_id)

        rir = generate_static_rir_with_mic(
            direct_path=direct,
            reflection_data=reflections,
            occlusion_result=occlusion,
            mic_pos=rec.position,
            fs=self.fs,
            c=self.c,
        )

        self._rir_cache[cache_key] = rir
        return rir

    def generate_all_rirs(
        self, scene_state: SceneState
    ) -> Dict[Tuple[str, str], RIR]:
        """Generate RIRs for all source × receiver pairs.

        Returns:
            Dict keyed by (source_id, receiver_id).
        """
        rirs: Dict[Tuple[str, str], RIR] = {}
        for src in scene_state.sources:
            if not src.active:
                continue
            for rec in scene_state.receivers:
                rirs[(src.source_id, rec.receiver_id)] = self.generate_rir(
                    scene_state, src.source_id, rec.receiver_id
                )
        return rirs

    def render_scene(
        self,
        scene_state: SceneState,
        source_signals: Dict[str, np.ndarray],
    ) -> Dict[str, np.ndarray]:
        """Render multi-channel observed signals at each receiver.

        For each receiver: sum convolutions of all active source signals with
        their respective RIRs.

        Args:
            scene_state: Current tick scene state.
            source_signals: {source_id: float32[N_samples]}

        Returns:
            {receiver_id: float32[N_out]} summed observed signal per receiver.
        """
        rirs = self.generate_all_rirs(scene_state)
        output: Dict[str, Optional[np.ndarray]] = {
            rec.receiver_id: None for rec in scene_state.receivers
        }

        for (src_id, rec_id), rir in rirs.items():
            if src_id not in source_signals:
                continue
            rendered = render_waveform(source_signals[src_id], rir, mode="full")
            if output[rec_id] is None:
                output[rec_id] = rendered
            else:
                # Zero-pad to same length then add
                a, b = output[rec_id], rendered
                n = max(len(a), len(b))
                buf = np.zeros(n, dtype=np.float32)
                buf[:len(a)] += a
                buf[:len(b)] += b
                output[rec_id] = buf

        # Replace None (no sources reached this receiver) with zeros
        n_out = max(
            (len(v) for v in output.values() if v is not None),
            default=1,
        )
        return {
            rec_id: (sig if sig is not None else np.zeros(n_out, dtype=np.float32))
            for rec_id, sig in output.items()
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_source(self, state: SceneState, src_id: str) -> SourceState:
        for s in state.sources:
            if s.source_id == src_id:
                return s
        raise KeyError(f"Source '{src_id}' not found in SceneState")

    def _get_receiver(self, state: SceneState, rec_id: str) -> ReceiverState:
        for r in state.receivers:
            if r.receiver_id == rec_id:
                return r
        raise KeyError(f"Receiver '{rec_id}' not found in SceneState")


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def process_scene(
    scene_state: SceneState,
    source_signals: Dict[str, np.ndarray],
    fs: int = 16000,
    ism_order: int = 3,
    seed: int = 0,
) -> Dict[str, np.ndarray]:
    """One-call render: scene_state + dry signals → observed signals per receiver.

    Args:
        scene_state: Fully assembled SceneState.
        source_signals: Dry audio per source {source_id: float32[N]}.
        fs: Sample rate in Hz.
        ism_order: ISM reflection order (1–10).

    Returns:
        {receiver_id: float32[N_out]}
    """
    engine = AcousticPropagationEngine(fs=fs, ism_order=ism_order, seed=seed)
    return engine.render_scene(scene_state, source_signals)
