"""
Frame-level VAD labels and overlap statistics (REQ-203, REQ-204).

Definition (REQ-204): a 1 ms frame is active when its RMS exceeds the stem's
maximum frame RMS by more than -40 dB.  Labels are computed on the *clean* dry
stem and shifted by the direct-path delay to the reference microphone.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np

VAD_THRESHOLD_DB = -40.0
VAD_FRAME_MS = 1.0

Segment = Tuple[int, int]


def frame_activity(signal: np.ndarray, fs: int, threshold_db: float = VAD_THRESHOLD_DB,
                   frame_ms: float = VAD_FRAME_MS) -> Tuple[np.ndarray, int]:
    """Boolean activity per frame and the frame length in samples."""
    x = np.asarray(signal, dtype=np.float64)
    hop = max(1, int(round(frame_ms * 1e-3 * fs)))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0, bool), hop
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1))
    peak = float(rms.max())
    if peak <= 0:
        return np.zeros(n, bool), hop
    return rms > peak * 10.0 ** (threshold_db / 20.0), hop


def vad_segments(signal: np.ndarray, fs: int, threshold_db: float = VAD_THRESHOLD_DB,
                 frame_ms: float = VAD_FRAME_MS, min_gap_ms: float = 0.0) -> List[Segment]:
    """Active segments [start, end) in samples; gaps shorter than ``min_gap_ms`` are bridged."""
    act, hop = frame_activity(signal, fs, threshold_db, frame_ms)
    segs: List[Segment] = []
    i = 0
    while i < len(act):
        if act[i]:
            j = i
            while j < len(act) and act[j]:
                j += 1
            segs.append((i * hop, j * hop))
            i = j
        else:
            i += 1
    if min_gap_ms > 0 and segs:
        gap = int(round(min_gap_ms * 1e-3 * fs))
        merged = [segs[0]]
        for s, e in segs[1:]:
            if s - merged[-1][1] < gap:
                merged[-1] = (merged[-1][0], e)
            else:
                merged.append((s, e))
        segs = merged
    return segs


def shift_segments(segs: Sequence[Segment], k: int, limit: int) -> List[Segment]:
    out = []
    for s, e in segs:
        s2, e2 = max(0, s + k), min(limit, e + k)
        if e2 > s2:
            out.append((int(s2), int(e2)))
    return out


def segments_to_mask(segs: Sequence[Segment], n: int) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    for s, e in segs:
        m[max(0, s):min(n, e)] = True
    return m


def overlap_stats(masks: Sequence[np.ndarray]) -> Dict[str, int]:
    """Counts of samples with >=1 and >=2 active sources."""
    if not masks:
        return {"any": 0, "multi": 0}
    stack = np.stack(masks).sum(axis=0)
    return {"any": int(np.sum(stack >= 1)), "multi": int(np.sum(stack >= 2))}


def overlap_ratio(masks: Sequence[np.ndarray]) -> float:
    st = overlap_stats(masks)
    return st["multi"] / st["any"] if st["any"] else 0.0


def boundary_f1(pred: np.ndarray, truth: np.ndarray, tol: int) -> float:
    """F1 of sample-level activity, ignoring samples within ``tol`` of a truth boundary."""
    pred = np.asarray(pred, bool)
    truth = np.asarray(truth, bool)
    edges = np.flatnonzero(np.diff(truth.astype(np.int8)) != 0)
    care = np.ones(len(truth), bool)
    for e in edges:
        care[max(0, e - tol + 1): e + tol + 1] = False
    p, t = pred[care], truth[care]
    tp = int(np.sum(p & t))
    fp = int(np.sum(p & ~t))
    fn = int(np.sum(~p & t))
    return 1.0 if tp + fp + fn == 0 else 2 * tp / (2 * tp + fp + fn)
