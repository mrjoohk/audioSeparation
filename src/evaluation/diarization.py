"""
Diarization error rate and a stream-based diarizer (REQ-402, audit F-05).

DER rules (fixed here so evaluator changes cannot reorder models):
* frame-based at ``frame_s`` (default 10 ms); overlapped speech is scored;
* optional ``collar_s`` around every reference boundary is excluded;
* reference/hypothesis speakers are mapped one-to-one to maximise overlap
  (Hungarian); unmapped hypothesis speakers count as confusion/false alarm;
* DER = (missed + false alarm + confusion) / reference speech.
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

Segment = Tuple[float, float]


def _frames(segs: Sequence[Segment], n: int, frame_s: float) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    for s, e in segs:
        m[int(round(s / frame_s)):int(round(e / frame_s))] = True
    return m


def der(reference: Mapping[str, Sequence[Segment]], hypothesis: Mapping[str, Sequence[Segment]],
        duration_s: float, frame_s: float = 0.01, collar_s: float = 0.0) -> Dict[str, float]:
    n = int(np.ceil(duration_s / frame_s))
    rk, hk = sorted(reference), sorted(hypothesis)
    R = np.array([_frames(reference[k], n, frame_s) for k in rk]).reshape(len(rk), n)
    H = np.array([_frames(hypothesis[k], n, frame_s) for k in hk]).reshape(len(hk), n)
    care = np.ones(n, dtype=bool)
    if collar_s > 0:
        c = int(round(collar_s / frame_s))
        for row in R:
            for e in np.flatnonzero(np.diff(row.astype(np.int8)) != 0):
                care[max(0, e - c + 1): e + c + 1] = False
    R, H = R[:, care], H[:, care]
    mapping = {}
    if len(rk) and len(hk):
        ov = (R[:, None, :] & H[None, :, :]).sum(axis=2)
        rows, cols = linear_sum_assignment(-ov)
        mapping = {int(r): int(c) for r, c in zip(rows, cols) if ov[r, c] > 0}
    n_ref = R.sum(axis=0)
    n_hyp = H.sum(axis=0)
    correct = np.zeros(R.shape[1])
    for r, c in mapping.items():
        correct += R[r] & H[c]
    total = float(n_ref.sum())
    miss = float(np.maximum(0, n_ref - n_hyp).sum())
    fa = float(np.maximum(0, n_hyp - n_ref).sum())
    conf = float((np.minimum(n_ref, n_hyp) - correct).sum())
    return {
        "der": (miss + fa + conf) / total if total else 0.0,
        "missed": miss / total if total else 0.0,
        "false_alarm": fa / total if total else 0.0,
        "confusion": conf / total if total else 0.0,
        "reference_s": total * frame_s,
        "mapping": {rk[r]: hk[c] for r, c in mapping.items()},
    }


def samples_to_seconds(segs: Sequence[Sequence[int]], fs: int) -> List[Segment]:
    return [(s / fs, e / fs) for s, e in segs]


def diarize_streams(streams: np.ndarray, fs: int, frame_s: float = 0.01,
                    threshold_db: float = -30.0, dominance_db: float = 6.0,
                    min_frames: int = 5) -> Dict[str, List[Segment]]:
    """One hypothesis speaker per separated stream: energy VAD + smoothing.

    A frame of stream k is active when its RMS is above ``threshold_db``
    relative to the loudest frame of all streams *and* within ``dominance_db``
    of the loudest stream in that frame, so leakage of another talker into a
    stream is not counted as speech.
    """
    hop = int(round(frame_s * fs))
    n = streams.shape[1] // hop
    rms = np.sqrt(np.mean(streams[:, : n * hop].reshape(len(streams), n, hop) ** 2, axis=2))
    ref = float(rms.max()) if rms.size else 0.0
    out: Dict[str, List[Segment]] = {}
    frame_max = rms.max(axis=0) if rms.size else np.zeros(n)
    for k, r in enumerate(rms):
        if ref > 0:
            act = (r > ref * 10 ** (threshold_db / 20.0)) & (r >= frame_max * 10 ** (-dominance_db / 20.0))
        else:
            act = np.zeros(n, bool)
        # close gaps and drop blips shorter than min_frames
        segs, i = [], 0
        while i < n:
            if act[i]:
                j = i
                while j < n and act[j]:
                    j += 1
                segs.append([i, j])
                i = j
            else:
                i += 1
        merged = []
        for s, e in segs:
            if merged and s - merged[-1][1] < min_frames:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        out[f"hyp{k}"] = [(s * frame_s, e * frame_s) for s, e in merged if e - s >= min_frames]
    return out
