"""
W100000 Spatial Simulator — UF-W134 Dynamic Scene Rendering
Implements UF-W134-01 through UF-W134-04.

UF-W134-01: should_rerender
UF-W134-02: select_segment_length
UF-W134-03: render_dynamic_scene
UF-W134-04: log_render_statistics
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import fftconvolve

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from simulator.types import (
    RIR,
    SceneState,
    SPEED_OF_SOUND,
)


# ---------------------------------------------------------------------------
# UF-W134-01: should_rerender
# ---------------------------------------------------------------------------

def should_rerender(
    prev_src_pos: np.ndarray,
    curr_src_pos: np.ndarray,
    prev_mic_pos: np.ndarray,
    curr_mic_pos: np.ndarray,
    threshold_m: float = 0.05,
) -> bool:
    """
    Determine whether a new RIR should be computed for this segment.

    Returns True if:
      ||curr_src_pos - prev_src_pos|| > threshold_m, OR
      ||curr_mic_pos - prev_mic_pos|| > threshold_m

    Parameters
    ----------
    prev_src_pos, curr_src_pos : array[3]
    prev_mic_pos, curr_mic_pos : array[3]
    threshold_m : float
        Default 5 cm (0.05 m).

    Returns
    -------
    bool
    """
    src_move = float(np.linalg.norm(
        np.asarray(curr_src_pos, dtype=np.float64) -
        np.asarray(prev_src_pos, dtype=np.float64)
    ))
    mic_move = float(np.linalg.norm(
        np.asarray(curr_mic_pos, dtype=np.float64) -
        np.asarray(prev_mic_pos, dtype=np.float64)
    ))
    return (src_move > threshold_m) or (mic_move > threshold_m)


# ---------------------------------------------------------------------------
# UF-W134-02: select_segment_length
# ---------------------------------------------------------------------------

def select_segment_length(mode: str = "balanced") -> int:
    """
    Return the segment length in samples for a given processing mode.

    Parameters
    ----------
    mode : str
        "fast"     → 512 samples
        "balanced" → 1024 samples
        "accurate" → 2048 samples

    Returns
    -------
    int
    """
    lut = {
        "fast": 512,
        "balanced": 1024,
        "accurate": 2048,
    }
    if mode not in lut:
        raise ValueError(
            f"Unknown mode '{mode}'. Choose from: fast, balanced, accurate."
        )
    return lut[mode]


# ---------------------------------------------------------------------------
# Internal: stub RIR generation
# ---------------------------------------------------------------------------

def _stub_rir(
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    fs: int,
    rir_len_samples: int = 2048,
) -> np.ndarray:
    """
    Stub RIR: single impulse at estimated propagation delay.

    Actual RIR generation requires a full propagation chain (ISM, ray tracing,
    etc.) via w124 or similar. This stub inserts an attenuated impulse at the
    direct-path delay to allow the rendering pipeline to function end-to-end.
    """
    dist = float(np.linalg.norm(
        np.asarray(src_pos, dtype=np.float64) -
        np.asarray(mic_pos, dtype=np.float64)
    ))
    dist = max(dist, 0.01)  # avoid divide-by-zero

    delay_samples = int(round(dist / SPEED_OF_SOUND * fs))
    attenuation = 1.0 / dist  # 1/r amplitude attenuation

    h = np.zeros(rir_len_samples, dtype=np.float32)
    if delay_samples < rir_len_samples:
        h[delay_samples] = float(attenuation)
    else:
        h[-1] = float(attenuation)

    return h


# ---------------------------------------------------------------------------
# UF-W134-03: render_dynamic_scene
# ---------------------------------------------------------------------------

def render_dynamic_scene(
    scene_states: List[SceneState],
    source_signals: Dict[str, np.ndarray],
    fs: int,
    segment_length_samples: int = 1024,
    rerender_threshold_m: float = 0.05,
) -> dict:
    """
    Render a dynamic scene using overlap-add convolution with adaptive RIR updates.

    For each source × receiver pair:
      - Split source signal into segments of segment_length_samples
      - For each segment: check should_rerender; if yes generate new RIR (stub);
        else reuse last RIR
      - Overlap-add (OLA) with 50% overlap and raised-cosine crossfade at boundaries

    Parameters
    ----------
    scene_states : List[SceneState]
        One entry per simulation tick.
    source_signals : dict {source_id: float32[N]}
        Input signals per source.
    fs : int
        Sample rate in Hz.
    segment_length_samples : int
        OLA segment size.
    rerender_threshold_m : float
        Position change threshold to trigger RIR update (default 5 cm).

    Returns
    -------
    dict with keys:
        "rendered_signals" : {receiver_id: float32[C×N_out]}
            C = number of sources (mixed per receiver)
        "render_stats" : dict with rendering statistics
    """
    if not scene_states:
        return {"rendered_signals": {}, "render_stats": {}}

    # Gather IDs
    source_ids = [s.source_id for s in scene_states[0].sources]
    receiver_ids = [r.receiver_id for r in scene_states[0].receivers]
    n_sources = len(source_ids)
    n_receivers = len(receiver_ids)
    tick_rate_hz = 50.0  # assume default; refine from scene states if possible

    hop = segment_length_samples // 2  # 50% overlap
    rir_len = segment_length_samples * 2  # stub RIR length

    # Raised cosine (Hann) window for crossfade
    window = np.hanning(segment_length_samples).astype(np.float32)

    # Determine total output length from source signals
    max_signal_len = 0
    for sid in source_ids:
        if sid in source_signals:
            max_signal_len = max(max_signal_len, len(source_signals[sid]))
    if max_signal_len == 0:
        return {"rendered_signals": {}, "render_stats": {"error": "no source signals"}}

    # Output: for each receiver, accumulate mixed signal
    # Shape: [n_receivers][max_signal_len + rir_len]
    out_len = max_signal_len + rir_len
    rendered: Dict[str, np.ndarray] = {
        rid: np.zeros(out_len, dtype=np.float32) for rid in receiver_ids
    }

    # Statistics
    n_rerenders_total = 0
    n_segments_total = 0
    segment_times_ms: List[float] = []

    # Build scene-state tick → positions lookup
    # Map: tick_id → {source_id: pos, receiver_id: pos}
    tick_to_src_pos: Dict[int, Dict[str, np.ndarray]] = {}
    tick_to_rec_pos: Dict[int, Dict[str, np.ndarray]] = {}
    for state in scene_states:
        tick_to_src_pos[state.tick_id] = {s.source_id: s.position for s in state.sources}
        tick_to_rec_pos[state.tick_id] = {r.receiver_id: r.position for r in state.receivers}

    # Pre-build tick list (ordered)
    tick_ids = sorted(tick_to_src_pos.keys())
    n_ticks = len(tick_ids)

    # Samples per tick
    samples_per_tick = fs / tick_rate_hz  # e.g. 320 at 16kHz, 50Hz

    for src_id in source_ids:
        if src_id not in source_signals:
            continue
        signal = np.asarray(source_signals[src_id], dtype=np.float32)
        N = len(signal)

        for rid_idx, rid in enumerate(receiver_ids):
            t_seg_start = time.perf_counter()

            # Last RIR and positions for rerender check
            last_rir: Optional[np.ndarray] = None
            prev_src_pos = np.zeros(3, dtype=np.float64)
            prev_mic_pos = np.zeros(3, dtype=np.float64)
            initialized = False

            # Accumulate output for this src→receiver pair
            pair_out = np.zeros(out_len, dtype=np.float32)

            # Iterate over segments with 50% hop
            seg_start = 0
            while seg_start < N:
                seg_end = min(seg_start + segment_length_samples, N)
                seg = signal[seg_start:seg_end]

                # Zero-pad if needed
                if len(seg) < segment_length_samples:
                    seg = np.pad(seg, (0, segment_length_samples - len(seg)))

                # Apply analysis window
                seg_windowed = seg * window

                # Determine tick for this segment center
                seg_center_sample = seg_start + hop
                # Map sample index to tick
                if n_ticks > 0 and samples_per_tick > 0:
                    tick_approx = int(seg_center_sample / samples_per_tick)
                    tick_approx = max(0, min(tick_approx, n_ticks - 1))
                    tick_id = tick_ids[tick_approx]
                else:
                    tick_id = tick_ids[0] if tick_ids else 0

                curr_src_pos = tick_to_src_pos.get(tick_id, {}).get(
                    src_id, np.zeros(3, dtype=np.float64)
                )
                curr_mic_pos = tick_to_rec_pos.get(tick_id, {}).get(
                    rid, np.zeros(3, dtype=np.float64)
                )

                # Rerender decision
                do_rerender = True
                if initialized:
                    do_rerender = should_rerender(
                        prev_src_pos, curr_src_pos,
                        prev_mic_pos, curr_mic_pos,
                        threshold_m=rerender_threshold_m,
                    )

                if do_rerender or last_rir is None:
                    last_rir = _stub_rir(curr_src_pos, curr_mic_pos, fs, rir_len)
                    prev_src_pos = curr_src_pos.copy()
                    prev_mic_pos = curr_mic_pos.copy()
                    initialized = True
                    n_rerenders_total += 1

                # Convolve segment with RIR
                conv = fftconvolve(seg_windowed, last_rir)
                conv = conv.astype(np.float32)

                # OLA: add to output at correct offset
                ola_start = seg_start
                ola_end = ola_start + len(conv)
                actual_end = min(ola_end, out_len)
                actual_conv_len = actual_end - ola_start
                if actual_conv_len > 0:
                    pair_out[ola_start:actual_end] += conv[:actual_conv_len]

                n_segments_total += 1
                seg_start += hop

            # Mix source into receiver output
            rendered[rid] += pair_out[:out_len]

            t_seg_end = time.perf_counter()
            segment_times_ms.append((t_seg_end - t_seg_start) * 1000.0)

    # Trim to original signal length
    rendered_trimmed: Dict[str, np.ndarray] = {}
    for rid, sig in rendered.items():
        rendered_trimmed[rid] = sig[:max_signal_len].astype(np.float32)

    # Compute statistics
    avg_seg_time_ms = float(np.mean(segment_times_ms)) if segment_times_ms else 0.0
    rerender_fraction = (
        float(n_rerenders_total) / float(n_segments_total)
        if n_segments_total > 0 else 0.0
    )

    render_stats = {
        "n_rerenders": n_rerenders_total,
        "total_segments": n_segments_total,
        "rerender_fraction": rerender_fraction,
        "avg_elapsed_ms_per_pair": avg_seg_time_ms,
        "n_sources": n_sources,
        "n_receivers": n_receivers,
        "segment_length_samples": segment_length_samples,
        "rerender_threshold_m": rerender_threshold_m,
        "output_length_samples": max_signal_len,
    }

    return {
        "rendered_signals": rendered_trimmed,
        "render_stats": render_stats,
    }


# ---------------------------------------------------------------------------
# UF-W134-04: log_render_statistics
# ---------------------------------------------------------------------------

def log_render_statistics(
    render_stats: dict,
    output_path: str,
) -> dict:
    """
    Log render statistics to a JSON file.

    Logged fields: n_rerenders, total_segments, rerender_fraction,
    elapsed_ms per segment, and all other stats in render_stats.

    Parameters
    ----------
    render_stats : dict
    output_path : str

    Returns
    -------
    dict (same as render_stats, with output_path added)
    """
    logged = dict(render_stats)
    logged["output_path"] = str(output_path)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(logged, f, indent=2)

    return logged


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W134 smoke test ===")

    # should_rerender
    p0 = np.array([0.0, 1.0, 0.0])
    p1 = np.array([0.1, 1.0, 0.0])  # 0.1 m move → over 5 cm threshold
    p2 = np.array([0.03, 1.0, 0.0])  # 0.03 m move → under threshold
    assert should_rerender(p0, p1, p0, p0) is True
    assert should_rerender(p0, p2, p0, p0) is False
    print("  should_rerender: OK")

    # select_segment_length
    assert select_segment_length("fast") == 512
    assert select_segment_length("balanced") == 1024
    assert select_segment_length("accurate") == 2048
    print("  select_segment_length: OK")

    # render_dynamic_scene with stub scene
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from simulator.uf.w111_room_geometry import define_room_primitive, generate_bounding_volume
    from simulator.uf.w131_trajectory import generate_source_trajectory
    from simulator.uf.w132_receiver_trajectory import generate_receiver_trajectory
    from simulator.uf.w133_sync import synchronize_scene_ticks

    room = define_room_primitive("shoebox", {"L": 6.0, "W": 5.0, "H": 3.0})
    bbox = generate_bounding_volume(room)

    duration_s = 0.5
    fs = 16000
    src_traj = generate_source_trajectory("linear", bbox, duration_s, seed=42)
    rec_traj = generate_receiver_trajectory("static", bbox, duration_s, seed=42)
    scene_states = synchronize_scene_ticks([src_traj], [rec_traj], room, [])

    # Sine wave signal
    N = int(duration_s * fs)
    t_arr = np.arange(N) / fs
    signal = (np.sin(2 * np.pi * 440.0 * t_arr) * 0.5).astype(np.float32)
    source_signals = {src_traj.source_id: signal}

    result = render_dynamic_scene(
        scene_states, source_signals, fs,
        segment_length_samples=512,
        rerender_threshold_m=0.05,
    )
    assert "rendered_signals" in result
    assert "render_stats" in result
    assert rec_traj.receiver_id in result["rendered_signals"]
    stats = result["render_stats"]
    print(f"  render_dynamic_scene: OK — {stats['n_rerenders']} rerenders / "
          f"{stats['total_segments']} segments "
          f"({stats['rerender_fraction']:.2%} rerender rate)")

    # log_render_statistics
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        tmp = tf.name
    logged = log_render_statistics(stats, tmp)
    assert logged["n_rerenders"] == stats["n_rerenders"]
    os.unlink(tmp)
    print("  log_render_statistics: OK")

    print("All UF-W134 smoke tests passed.")
