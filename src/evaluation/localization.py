"""
Localization and tracking: GCC-PHAT TDOA, direction recovery, error metrics.

REQ-W03 note (audit F-09): a single microphone pair measures one TDOA, which
fixes only the *cone angle* to the pair axis.  Directions on the same cone
(e.g. front/back, or any rotation about the axis) give identical delays, so a
full 3-D direction cannot be recovered from one pair.  Tests therefore check
(a) the direct-path delay difference against geometry and (b) the cone angle,
or azimuth only when the source is restricted to the array plane.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

SPEED_OF_SOUND = 343.0


def gcc_phat(
    x: np.ndarray,
    y: np.ndarray,
    fs: int,
    max_tau: Optional[float] = None,
    interp: int = 16,
) -> float:
    """Delay of ``y`` relative to ``x`` in seconds (positive: y lags x)."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n = len(x) + len(y)
    X = np.fft.rfft(x, n=n)
    Y = np.fft.rfft(y, n=n)
    R = Y * np.conj(X)
    R /= np.abs(R) + 1e-15
    cc = np.fft.irfft(R, n=interp * n)
    max_shift = interp * n // 2
    if max_tau is not None:
        max_shift = min(int(interp * fs * max_tau), max_shift)
    cc = np.concatenate((cc[-max_shift:], cc[: max_shift + 1]))
    shift = int(np.argmax(np.abs(cc))) - max_shift
    return shift / float(interp * fs)


def cone_angle_deg(tau: float, mic_distance: float, c: float = SPEED_OF_SOUND) -> float:
    """Angle (deg, 0–180) between the pair axis (mic0→mic1) and the source direction.

    ``tau`` is the delay of mic1 relative to mic0.  A source towards mic1 reaches
    it first (tau < 0) and gives an angle < 90°.
    """
    cosv = float(np.clip(-tau * c / mic_distance, -1.0, 1.0))
    return math.degrees(math.acos(cosv))


def true_cone_angle_deg(src: Sequence[float], mic0: Sequence[float], mic1: Sequence[float]) -> float:
    """Far-field cone angle between axis mic0→mic1 and direction centre→source."""
    m0, m1, s = (np.asarray(v, float) for v in (mic0, mic1, src))
    axis = (m1 - m0) / np.linalg.norm(m1 - m0)
    d = s - (m0 + m1) / 2.0
    return math.degrees(math.acos(float(np.clip(np.dot(axis, d) / np.linalg.norm(d), -1, 1))))


def angular_error_deg(az1: float, el1: float, az2: float, el2: float) -> float:
    """Great-circle angle (deg) between two directions given as az/el in degrees.

    Convention (simulator): az = atan2(dx, dz), el = asin(dy/|d|) (Y-up).
    """
    def vec(az, el):
        a, e = math.radians(az), math.radians(el)
        return np.array([math.cos(e) * math.sin(a), math.sin(e), math.cos(e) * math.cos(a)])
    v1, v2 = vec(az1, el1), vec(az2, el2)
    return math.degrees(math.acos(float(np.clip(np.dot(v1, v2), -1.0, 1.0))))


def wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


# ---------------------------------------------------------------------------
# Tracking metrics
# ---------------------------------------------------------------------------

def tracking_metrics(
    truth: Dict[str, List[Tuple[float, float]]],
    estimate: Dict[str, List[Tuple[float, float]]],
    times: Sequence[float],
    gate_deg: float = 20.0,
) -> Dict[str, float]:
    """Frame-wise azimuth tracking metrics.

    Args:
        truth / estimate: {track_id: [(az_deg, el_deg) or None per frame]}.
        gate_deg: an estimate within this angle of a truth track counts as a hit.

    Returns:
        {"mean_error_deg", "recall", "precision", "id_switches", "fragmentations"}
        Frames are matched greedily by smallest angular error per frame.
        ``fragmentations`` counts truth tracks whose matched run is interrupted.
    """
    tids, eids = list(truth), list(estimate)
    errs: List[float] = []
    n_truth = n_est = n_hit = 0
    last_match: Dict[str, Optional[str]] = {t: None for t in tids}
    matched_prev: Dict[str, bool] = {t: False for t in tids}
    switches = frags = 0
    started: Dict[str, bool] = {t: False for t in tids}
    for f in range(len(times)):
        tv = {t: truth[t][f] for t in tids if truth[t][f] is not None}
        ev = {e: estimate[e][f] for e in eids if estimate[e][f] is not None}
        n_truth += len(tv)
        n_est += len(ev)
        pairs = sorted(
            (angular_error_deg(*tv[t], *ev[e]), t, e) for t in tv for e in ev
        )
        used_t, used_e = set(), set()
        for err, t, e in pairs:
            if t in used_t or e in used_e or err > gate_deg:
                continue
            used_t.add(t)
            used_e.add(e)
            errs.append(err)
            n_hit += 1
            if last_match[t] is not None and last_match[t] != e:
                switches += 1
            if started[t] and not matched_prev[t]:
                frags += 1
            last_match[t] = e
            started[t] = True
        for t in tids:
            if t in tv:
                matched_prev[t] = t in used_t
    return {
        "mean_error_deg": float(np.mean(errs)) if errs else float("nan"),
        "recall": n_hit / n_truth if n_truth else float("nan"),
        "precision": n_hit / n_est if n_est else float("nan"),
        "id_switches": float(switches),
        "fragmentations": float(frags),
    }


# ---------------------------------------------------------------------------
# Tracking evaluation on dynamic scenes (W414)
# ---------------------------------------------------------------------------

def track_azimuths(mixture: np.ndarray, fs: int, mic_pos: np.ndarray, ref: int, n_sources: int,
                   frame_s: float = 0.1):
    """Frame-wise SRP-PHAT azimuths with nearest-neighbour track continuation.

    Returns (frame_times_s, {track_id: [(az_deg, 0.0) or None]}).
    """
    from training.dsp import srp_phat, stft_c
    hop = int(frame_s * fs)
    n = mixture.shape[1] // hop
    times, tracks = [], {f"t{k}": [] for k in range(n_sources)}
    last = [None] * n_sources
    for i in range(n):
        seg = mixture[:, i * hop:(i + 1) * hop]
        if float(np.mean(seg ** 2)) < 1e-10:
            for k in range(n_sources):
                tracks[f"t{k}"].append(None)
            times.append(i * frame_s)
            continue
        est = srp_phat(stft_c(seg.astype(float), fs), fs, mic_pos, ref, n_sources)
        assigned = [None] * n_sources
        free = list(est)
        for k in range(n_sources):
            if last[k] is not None and free:
                j = int(np.argmin([abs(wrap_deg(e - last[k])) for e in free]))
                assigned[k] = free.pop(j)
        for k in range(n_sources):
            if assigned[k] is None and free:
                assigned[k] = free.pop(0)
            last[k] = assigned[k] if assigned[k] is not None else last[k]
            tracks[f"t{k}"].append(None if assigned[k] is None else (float(assigned[k]), 0.0))
        times.append(i * frame_s)
    return times, tracks


def truth_tracks(doa_trace: dict, times, vad: dict, fs: int):
    """Ground-truth azimuth per frame from a manifest ``doa_trace`` (active frames only)."""
    out = {}
    for s, tr in doa_trace.items():
        t_arr = np.array([r[0] for r in tr])
        seq = []
        for t in times:
            n = int((t + 0.05) * fs)
            active = any(a <= n < b for a, b in vad.get(s, []))
            if not active:
                seq.append(None)
                continue
            r = tr[int(np.argmin(np.abs(t_arr - (t + 0.05))))]
            seq.append(((r[1]) % 360.0, 0.0))
        out[s] = seq
    return out
