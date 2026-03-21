"""
IF-W141..W144: Capture Device Realism — Integration Module
Composes microphone response, array geometry, noise/gain, and codec impairment UFs
into a CaptureDeviceChain API.
"""
from __future__ import annotations

import sys
import os
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from simulator.types import (
    ArrayConfig, ImpairmentSpec, MicSpec, SceneConfig,
)
from simulator.uf.w141_mic_response import (
    apply_frequency_response, apply_sensitivity_variation,
    apply_directional_pattern,
)
from simulator.uf.w142_array_geometry import (
    perturb_array_positions, model_clock_skew,
)
from simulator.uf.w143_noise_gain import (
    add_self_noise, apply_gain_agc, apply_clipping,
)
from simulator.uf.w144_codec import (
    apply_bandwidth_limit, apply_codec_artifacts,
    apply_packet_loss, tag_impairment_conditions,
)
from simulator.uf.w151_config import derive_subsystem_seeds


class CaptureDeviceChain:
    """Applies the full capture device processing chain to rendered signals.

    Chain order:
        raw signals → mic frequency response → directional pattern
                    → sensitivity variation → array position errors
                    → self-noise & gain → clipping → codec/impairment
    """

    def __init__(self, config: SceneConfig, seed: int = 42) -> None:
        self.config = config
        self.seed = seed
        self.fs = config.sample_rate
        self._seeds = derive_subsystem_seeds(seed, ["noise", "codec", "array"])

    # ------------------------------------------------------------------
    # Stage: microphone responses
    # ------------------------------------------------------------------

    def apply_mic_responses(
        self,
        signals: np.ndarray,           # float32[C×N]
        mic_specs: List[MicSpec],
        doa_list: Optional[List[dict]] = None,  # [{doa_az_rad, doa_el_rad}] per channel
    ) -> np.ndarray:
        """Apply frequency response and directional pickup to each channel.

        Args:
            signals: float32[C×N] multichannel signal.
            mic_specs: One MicSpec per channel.
            doa_list: DOA per channel for directional pattern (optional).

        Returns:
            float32[C×N] filtered signals.
        """
        C, N = signals.shape
        out = np.zeros_like(signals)

        for c in range(min(C, len(mic_specs))):
            spec = mic_specs[c]
            ch = signals[c].copy()

            # Frequency response
            if spec.freq_response_db is not None and len(spec.freq_response_db) > 0:
                ch = apply_frequency_response(
                    ch, spec.freq_response_db, spec.freq_bins_hz, self.fs
                )

            # Directional pattern
            if doa_list and c < len(doa_list):
                az = float(doa_list[c].get("doa_az_rad", 0.0))
                el = float(doa_list[c].get("doa_el_rad", 0.0))
                _, ch = apply_directional_pattern(ch, az, el, spec.pattern_type)

            out[c] = ch

        # Sensitivity variation
        sensitivities = np.array([s.sensitivity_db for s in mic_specs[:C]])
        if len(sensitivities) < C:
            sensitivities = np.pad(sensitivities, (0, C - len(sensitivities)))
        out = apply_sensitivity_variation(out, sensitivities)

        return out.astype(np.float32)

    # ------------------------------------------------------------------
    # Stage: array position errors
    # ------------------------------------------------------------------

    def apply_array_errors(self, array_config: ArrayConfig) -> ArrayConfig:
        """Apply position perturbation and clock skew to array geometry.

        Args:
            array_config: Nominal array configuration.

        Returns:
            Updated ArrayConfig with effective_positions and clock_skew_samples.
        """
        arr_seed = self._seeds.get("array", self.seed)
        sigma = 0.002   # 2 mm default perturbation

        updated = perturb_array_positions(array_config, sigma_m=sigma, seed=arr_seed)
        updated = model_clock_skew(updated, max_skew_samples=1, fs=self.fs,
                                   seed=(arr_seed + 1) & 0x7FFFFFFF)
        return updated

    # ------------------------------------------------------------------
    # Stage: noise and gain
    # ------------------------------------------------------------------

    def apply_noise_gain(
        self,
        signals: np.ndarray,   # float32[C×N]
    ) -> Tuple[np.ndarray, List[float]]:
        """Apply self-noise, gain, and optional AGC/clipping.

        Noise and gain parameters are read from config.receivers[0] if present,
        otherwise defaults are used.

        Returns:
            (degraded_signals: float32[C×N], snr_per_channel: List[float])
        """
        noise_seed = self._seeds.get("noise", self.seed)
        C, N = signals.shape

        # Default noise/gain parameters
        noise_floor = -60.0   # dBFS
        gain_db = 0.0
        clip_threshold = 0.0  # dBFS

        # Try to read from config
        if self.config.receivers:
            rec0 = self.config.receivers[0]
            noise_floor = float(rec0.get("noise_floor_dbfs", noise_floor))
            gain_db = float(rec0.get("gain_db", gain_db))
            clip_threshold = float(rec0.get("clip_threshold_dbfs", clip_threshold))

        out = np.zeros_like(signals)
        snr_list: List[float] = []

        for c in range(C):
            ch, snr = add_self_noise(
                signals[c], noise_floor, self.fs,
                seed=(noise_seed + c) & 0x7FFFFFFF,
            )
            ch = apply_gain_agc(ch, gain_db)
            ch, _, _ = apply_clipping(ch, clip_threshold)
            out[c] = ch
            snr_list.append(snr)

        return out.astype(np.float32), snr_list

    # ------------------------------------------------------------------
    # Stage: codec / channel impairments
    # ------------------------------------------------------------------

    def apply_impairments(
        self,
        signals: np.ndarray,         # float32[C×N]
    ) -> Tuple[np.ndarray, dict]:
        """Apply codec/channel impairments from config.

        Returns:
            (impaired_signals: float32[C×N], impairment_metadata: dict)
        """
        codec_seed = self._seeds.get("codec", self.seed)
        imp_cfg = self.config.impairments or {}
        imp_type = imp_cfg.get("type", "none")

        spec = ImpairmentSpec(
            impairment_type=imp_type,
            bandwidth_hz=imp_cfg.get("bandwidth_hz"),
            packet_error_rate=imp_cfg.get("packet_error_rate"),
            segment_duration_ms=imp_cfg.get("segment_duration_ms", 20.0),
        )

        C, N = signals.shape
        out = np.zeros_like(signals)
        metadata: dict = {"type": imp_type, "applied": imp_type != "none"}

        for c in range(C):
            ch = signals[c].copy()

            if imp_type == "bandwidth" and spec.bandwidth_hz:
                ch = apply_bandwidth_limit(ch, spec.bandwidth_hz, self.fs)

            elif imp_type == "codec":
                ch = apply_codec_artifacts(ch, self.fs)

            elif imp_type == "packet_loss" and spec.packet_error_rate is not None:
                ch, n_dropped, total = apply_packet_loss(
                    ch, self.fs,
                    packet_error_rate=spec.packet_error_rate,
                    segment_duration_ms=spec.segment_duration_ms or 20.0,
                    seed=(codec_seed + c) & 0x7FFFFFFF,
                )
                metadata["n_dropped_segments"] = n_dropped
                metadata["total_segments"] = total

            out[c] = ch

        tags = tag_impairment_conditions(spec, metadata)
        metadata.update(tags)
        return out.astype(np.float32), metadata

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    def process_full_chain(
        self,
        raw_signals: np.ndarray,       # float32[C×N]
        mic_specs: List[MicSpec],
        array_config: Optional[ArrayConfig] = None,
        doa_list: Optional[List[dict]] = None,
    ) -> Tuple[np.ndarray, dict]:
        """Apply all capture stages in sequence.

        Stages: mic_response → array_errors → noise_gain → impairments

        Args:
            raw_signals: float32[C×N] rendered multichannel signal.
            mic_specs: Per-channel microphone specifications.
            array_config: Array topology (for position/clock errors).
            doa_list: DOA per channel for directional patterns.

        Returns:
            (processed_signals: float32[C×N], chain_metadata: dict)
        """
        metadata: dict = {}

        # Stage 1: mic responses
        sig = self.apply_mic_responses(raw_signals, mic_specs, doa_list)

        # Stage 2: array geometry errors
        if array_config is not None:
            updated_array = self.apply_array_errors(array_config)
            metadata["array_position_perturbation_m"] = float(
                np.mean(np.linalg.norm(
                    updated_array.effective_positions - array_config.nominal_positions,
                    axis=1,
                ))
            ) if updated_array.effective_positions is not None else 0.0
            metadata["clock_skew_samples"] = (
                updated_array.clock_skew_samples.tolist()
                if updated_array.clock_skew_samples is not None else []
            )

        # Stage 3: noise and gain
        sig, snr_list = self.apply_noise_gain(sig)
        metadata["snr_per_channel_db"] = snr_list

        # Stage 4: impairments
        sig, imp_meta = self.apply_impairments(sig)
        metadata["impairment"] = imp_meta

        return sig, metadata


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

def apply_device_chain(
    raw_signals: np.ndarray,
    config: SceneConfig,
    mic_specs: List[MicSpec],
    array_config: Optional[ArrayConfig] = None,
    doa_list: Optional[List[dict]] = None,
) -> Tuple[np.ndarray, dict]:
    """One-call device chain application.

    Args:
        raw_signals: float32[C×N] rendered signals.
        config: Validated SceneConfig.
        mic_specs: Per-channel mic specs.
        array_config: Optional array geometry.
        doa_list: Optional DOA per channel.

    Returns:
        (processed_signals: float32[C×N], chain_metadata: dict)
    """
    chain = CaptureDeviceChain(config, seed=config.seed)
    return chain.process_full_chain(raw_signals, mic_specs, array_config, doa_list)
