"""
W100000 Spatial Simulator — UF-W144 Codec and Channel Impairments
Implements UF-W144-01 through UF-W144-04.

UF-W144-01: apply_bandwidth_limit
UF-W144-02: apply_codec_artifacts
UF-W144-03: apply_packet_loss
UF-W144-04: tag_impairment_conditions
"""
from __future__ import annotations

import math
import os
import sys
import warnings
from typing import Optional

import numpy as np
from scipy.signal import firwin, fftconvolve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from simulator.types import ImpairmentSpec

# Physical constraints
PER_MIN: float = 0.0
PER_MAX: float = 0.2


# ---------------------------------------------------------------------------
# UF-W144-01: apply_bandwidth_limit
# ---------------------------------------------------------------------------

def apply_bandwidth_limit(
    signal: np.ndarray,
    bandwidth_hz: float,
    fs: int,
    filter_order: int = 128,
) -> np.ndarray:
    """
    Apply a lowpass FIR filter to limit signal bandwidth.

    Parameters
    ----------
    signal : float32[N]
    bandwidth_hz : float
        Lowpass cutoff frequency in Hz.
    fs : int
        Sample rate.
    filter_order : int
        FIR filter order (filter has filter_order+1 taps).

    Returns
    -------
    float32[N]  — same length as input
    """
    signal = np.asarray(signal, dtype=np.float32)
    N = len(signal)

    nyquist = fs / 2.0
    normalized_cutoff = float(np.clip(bandwidth_hz / nyquist, 1e-6, 1.0 - 1e-6))

    # Always use odd number of taps for Type I linear-phase FIR
    n_taps = filter_order + 1
    if n_taps % 2 == 0:
        n_taps += 1

    # Design lowpass FIR
    h = firwin(n_taps, normalized_cutoff, window="hamming").astype(np.float32)

    # Apply via fftconvolve; truncate to original length
    filtered = fftconvolve(signal, h)[:N].astype(np.float32)

    return filtered


# ---------------------------------------------------------------------------
# UF-W144-02: apply_codec_artifacts
# ---------------------------------------------------------------------------

def apply_codec_artifacts(
    signal: np.ndarray,
    fs: int,
    bitrate_kbps: float = 32.0,
) -> np.ndarray:
    """
    Simulate lossy codec artifacts.

    Steps:
      1. Modest lowpass (bandwidth based on bitrate).
      2. Add spectrally shaped quantization noise:
         - Flat noise up to 3 kHz.
         - +6 dB boost above 3 kHz.

    Quantization level ≈ signal_rms * 10^(-bitrate_kbps/20) * 0.01

    Parameters
    ----------
    signal : float32[N]
    fs : int
    bitrate_kbps : float
        Bitrate in kbps (used to scale noise and set bandwidth).

    Returns
    -------
    float32[N]
    """
    signal = np.asarray(signal, dtype=np.float32)
    N = len(signal)

    # Step 1: Apply bandwidth limit based on bitrate
    # Approximate Nyquist bandwidth from bitrate (rough heuristic)
    # 8 kbps → 4 kHz, 32 kbps → 8 kHz (telephony band), 64 kbps → 16 kHz
    bandwidth_hz = min(float(bitrate_kbps) * 250.0, fs / 2.0 * 0.95)
    bandwidth_hz = max(bandwidth_hz, 500.0)
    processed = apply_bandwidth_limit(signal, bandwidth_hz, fs, filter_order=64)

    # Step 2: Spectrally shaped quantization noise
    signal_rms = float(np.sqrt(np.mean(processed.astype(np.float64) ** 2)))
    if signal_rms < 1e-12:
        return processed

    # Quantization level
    quant_level = signal_rms * (10.0 ** (-float(bitrate_kbps) / 20.0)) * 0.01

    # Generate flat white noise
    rng = np.random.default_rng(seed=int(bitrate_kbps * 1000) % (2**31))
    quant_noise = (rng.standard_normal(N) * quant_level).astype(np.float32)

    # Boost noise above 3 kHz by +6 dB using a highpass shelf
    crossover_hz = 3000.0
    nyquist = fs / 2.0
    if crossover_hz < nyquist * 0.95:
        norm_cut = crossover_hz / nyquist
        # Highpass filter for the boost component
        n_taps = 65
        h_hp = firwin(n_taps, norm_cut, pass_zero=False, window="hamming").astype(np.float32)
        high_freq_noise = fftconvolve(quant_noise, h_hp)[:N].astype(np.float32)
        # Boost high-freq noise by 6 dB (×2)
        quant_noise_shaped = quant_noise + high_freq_noise * 1.0  # total = flat + high (+6dB above cross)
    else:
        quant_noise_shaped = quant_noise

    result = (processed + quant_noise_shaped).astype(np.float32)
    return result


# ---------------------------------------------------------------------------
# UF-W144-03: apply_packet_loss
# ---------------------------------------------------------------------------

def apply_packet_loss(
    signal: np.ndarray,
    fs: int,
    packet_error_rate: float = 0.05,
    segment_duration_ms: float = 20.0,
    seed: int = 42,
) -> tuple:
    """
    Simulate packet loss by zeroing randomly selected segments.

    Each segment has duration = segment_duration_ms ms = segment_duration_ms * fs / 1000 samples.
    Each segment is dropped independently with probability = packet_error_rate.

    Parameters
    ----------
    signal : float32[N]
    fs : int
    packet_error_rate : float
        Probability of dropping each segment (PER ∈ [0, 0.2]).
    segment_duration_ms : float
        Duration of each packet/segment in milliseconds.
    seed : int

    Returns
    -------
    (impaired: float32[N], n_dropped_segments: int, total_segments: int)
    """
    signal = np.asarray(signal, dtype=np.float32)
    N = len(signal)

    # Validate PER
    if packet_error_rate < PER_MIN or packet_error_rate > PER_MAX:
        warnings.warn(
            f"apply_packet_loss: packet_error_rate={packet_error_rate:.4f} outside "
            f"valid range [{PER_MIN}, {PER_MAX}]. Clamping.",
            UserWarning,
            stacklevel=2,
        )
        packet_error_rate = float(np.clip(packet_error_rate, PER_MIN, PER_MAX))

    segment_samples = int(round(segment_duration_ms * fs / 1000.0))
    if segment_samples < 1:
        segment_samples = 1

    # Number of complete segments + partial last segment
    total_segments = math.ceil(N / segment_samples)

    rng = np.random.default_rng(seed)
    # Draw Bernoulli drops for each segment
    drop_flags = rng.random(total_segments) < packet_error_rate

    impaired = signal.copy()
    n_dropped = 0

    for seg_idx in range(total_segments):
        seg_start = seg_idx * segment_samples
        seg_end = min(seg_start + segment_samples, N)
        if drop_flags[seg_idx]:
            impaired[seg_start:seg_end] = 0.0
            n_dropped += 1

    return (impaired, int(n_dropped), int(total_segments))


# ---------------------------------------------------------------------------
# UF-W144-04: tag_impairment_conditions
# ---------------------------------------------------------------------------

def tag_impairment_conditions(
    impairment_spec: ImpairmentSpec,
    results: dict,
) -> dict:
    """
    Tag a results dict with impairment metadata.

    Parameters
    ----------
    impairment_spec : ImpairmentSpec
    results : dict
        Output dict from apply_* functions (may contain n_dropped_segments etc.)

    Returns
    -------
    dict with fields:
        type, parameters, applied, n_dropped_segments (if applicable)
    """
    metadata: dict = {
        "type": impairment_spec.impairment_type,
        "parameters": {},
        "applied": True,
    }

    itype = impairment_spec.impairment_type

    if itype == "bandwidth":
        metadata["parameters"]["bandwidth_hz"] = impairment_spec.bandwidth_hz

    elif itype == "codec":
        metadata["parameters"]["packet_error_rate"] = impairment_spec.packet_error_rate
        metadata["parameters"]["segment_duration_ms"] = impairment_spec.segment_duration_ms

    elif itype == "packet_loss":
        metadata["parameters"]["packet_error_rate"] = impairment_spec.packet_error_rate
        metadata["parameters"]["segment_duration_ms"] = impairment_spec.segment_duration_ms
        if "n_dropped_segments" in results:
            metadata["n_dropped_segments"] = results["n_dropped_segments"]
        if "total_segments" in results:
            metadata["total_segments"] = results["total_segments"]

    elif itype == "none":
        metadata["applied"] = False

    else:
        metadata["applied"] = False
        warnings.warn(
            f"tag_impairment_conditions: unknown impairment_type '{itype}'.",
            UserWarning,
            stacklevel=2,
        )

    # Merge any additional results fields
    for k, v in results.items():
        if k not in metadata:
            metadata[k] = v

    return metadata


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W144 smoke test ===")
    fs = 16000
    N = 16000
    t = np.arange(N) / fs

    # White noise test signal
    rng = np.random.default_rng(0)
    signal = (rng.standard_normal(N) * 0.1).astype(np.float32)

    # apply_bandwidth_limit at 4 kHz
    limited = apply_bandwidth_limit(signal, 4000.0, fs, filter_order=128)
    assert len(limited) == N, "Output length mismatch"
    assert limited.dtype == np.float32
    # Verify energy above 5 kHz is attenuated
    fft_limited = np.abs(np.fft.rfft(limited))
    fft_full = np.abs(np.fft.rfft(signal))
    freqs = np.fft.rfftfreq(N, 1.0 / fs)
    high_idx = freqs > 5000.0
    low_idx = (freqs > 100.0) & (freqs < 3500.0)
    energy_high = float(np.mean(fft_limited[high_idx] ** 2))
    energy_low = float(np.mean(fft_limited[low_idx] ** 2))
    ratio_db = 10.0 * math.log10(energy_high / (energy_low + 1e-30))
    print(f"  apply_bandwidth_limit: energy ratio high/low = {ratio_db:.1f} dB")
    assert ratio_db < -20.0, f"High-freq energy not sufficiently attenuated: {ratio_db:.1f} dB"
    print("  apply_bandwidth_limit: OK")

    # apply_codec_artifacts
    codec_out = apply_codec_artifacts(signal, fs, bitrate_kbps=32.0)
    assert len(codec_out) == N
    assert codec_out.dtype == np.float32
    print("  apply_codec_artifacts: OK")

    # apply_packet_loss: PER=0.1, 100 segments of 20 ms → N=32000 for 2 s at 16kHz
    N_pl = int(2.0 * fs)  # 2 seconds
    sig_pl = (rng.standard_normal(N_pl) * 0.1).astype(np.float32)
    impaired, n_dropped, total_seg = apply_packet_loss(sig_pl, fs, packet_error_rate=0.1, seed=42)
    assert total_seg == 100  # 2.0s / 0.02s = 100 segments
    print(f"  apply_packet_loss: {n_dropped}/{total_seg} segments dropped "
          f"(PER target=0.1, actual={n_dropped/total_seg:.2f})")
    assert 5 <= n_dropped <= 20, f"Dropped count {n_dropped} out of expected [5, 20]"
    print("  apply_packet_loss: OK")

    # tag_impairment_conditions
    spec = ImpairmentSpec(
        impairment_type="packet_loss",
        packet_error_rate=0.1,
        segment_duration_ms=20.0,
    )
    tagged = tag_impairment_conditions(
        spec,
        {"n_dropped_segments": n_dropped, "total_segments": total_seg}
    )
    assert tagged["type"] == "packet_loss"
    assert tagged["applied"] is True
    assert tagged["n_dropped_segments"] == n_dropped
    print(f"  tag_impairment_conditions: OK ({tagged})")

    print("All UF-W144 smoke tests passed.")
