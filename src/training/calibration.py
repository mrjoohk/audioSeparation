"""
Simulator calibration from unlabeled recordings (REQ-302; design §6.3).

1. :func:`blind_rt60` estimates RT60 from a reverberant recording without an
   RIR.  Free decays after sound offsets are located on a 10 ms log-energy
   envelope; each decay of >= 20 dB is fitted (T20 × 3) and the median of the
   per-decay values is the estimate.  (Tuned on rendered rooms with Sabine
   targets 0.3 / 0.5 / 0.8 s: medians 0.305 / 0.468 / 0.871 s.)
2. :func:`fit_profile` turns per-session estimates into a calibration profile
   (id, data version, sessions used, RT60 samples and range).
3. W2 consumes the profile (``ScenarioPrior.calibration``): each scene draws a
   target RT60 and sets a uniform absorption by inverse Sabine
   (:func:`alpha_for_rt60`).
4. :func:`kl_divergence` compares measured and regenerated RT60 distributions
   (REQ-302: KL <= 0.1).  Distribution match is a diagnostic; adoption is
   decided by dev task gain (design §6.3).
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np

FRAME_S = 0.01


def _envelope_db(x: np.ndarray, fs: int, frame_s: float = FRAME_S) -> np.ndarray:
    hop = int(round(frame_s * fs))
    n = len(x) // hop
    e = np.mean(np.asarray(x[: n * hop], float).reshape(n, hop) ** 2, axis=1)
    return 10 * np.log10(e + 1e-20)


def decay_estimates(x: np.ndarray, fs: int, min_drop_db: float = 20.0,
                    min_len_s: float = 0.05, tolerance_db: float = 1.0) -> List[float]:
    """RT60 estimates (s) of every free-decay region with at least ``min_drop_db`` drop."""
    env = _envelope_db(x, fs)
    floor = np.percentile(env, 10)
    out = []
    i = 1
    n = len(env)
    while i < n - 1:
        if env[i] >= env[i - 1] and env[i] > env[i + 1] and env[i] > floor + min_drop_db + 5:
            j = i
            lo = env[i]
            while j + 1 < n and env[j + 1] <= lo + tolerance_db:
                j += 1
                lo = min(lo, env[j])
                if env[i] - lo >= min_drop_db + 5 or env[j] <= floor + 3:
                    break
            seg = env[i:j + 1]
            if len(seg) * FRAME_S >= min_len_s and seg[0] - seg.min() >= min_drop_db:
                # T20: fit from -5 dB to -25 dB below the start
                k0 = int(np.argmax(seg <= seg[0] - 5))
                k1 = int(np.argmax(seg <= seg[0] - 25)) if np.any(seg <= seg[0] - 25) else len(seg) - 1
                if k1 - k0 >= 3:
                    t = np.arange(k0, k1 + 1) * FRAME_S
                    slope = np.polyfit(t, seg[k0:k1 + 1], 1)[0]
                    if slope < 0:
                        out.append(-60.0 / slope)
            i = j + 1
        else:
            i += 1
    return out


def blind_rt60(x: np.ndarray, fs: int, percentile: float = 50.0) -> Optional[float]:
    """Median T20-based RT60; falls back to 15 dB decays (T15) in noisy recordings.
    Returns None when no free decay has enough dynamic range."""
    est = decay_estimates(x, fs)
    if not est:
        est = decay_estimates(x, fs, min_drop_db=15.0)
    return float(np.percentile(est, percentile)) if est else None


def fit_profile(estimates: Mapping[str, float], data_version: str,
                profile_id: Optional[str] = None) -> dict:
    vals = np.array([v for v in estimates.values() if v is not None], float)
    if vals.size == 0:
        raise ValueError("no RT60 estimates")
    body = {"rt60_samples": sorted(float(v) for v in vals), "data_version": data_version}
    pid = profile_id or "calib-" + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:10]
    return {
        "id": pid,
        "data_version": data_version,
        "fit_sessions": sorted(k for k, v in estimates.items() if v is not None),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rt60_samples": body["rt60_samples"],
        "parameter_ranges": {"rt60_s": [float(np.percentile(vals, 5)), float(np.percentile(vals, 95))]},
        "rt60_median_s": float(np.median(vals)),
        "method": "blind_rt60 (T20 on free decays, median)",
    }


def alpha_for_rt60(dims: Mapping[str, float], rt60_s: float) -> float:
    """Uniform absorption giving Sabine RT60 = rt60_s (clipped to [0.01, 0.99])."""
    L, W, H = dims["L"], dims["W"], dims["H"]
    V = L * W * H
    S = 2 * (L * W + L * H + W * H)
    return float(np.clip(0.161 * V / (S * rt60_s), 0.01, 0.99))


def kl_divergence(p_samples: Sequence[float], q_samples: Sequence[float],
                  bins: Optional[Sequence[float]] = None, eps: float = 1e-3) -> float:
    """KL(P || Q) of two sample sets on shared histogram bins (with additive smoothing)."""
    p = np.asarray(p_samples, float)
    q = np.asarray(q_samples, float)
    if bins is None:
        lo, hi = min(p.min(), q.min()), max(p.max(), q.max())
        bins = np.linspace(lo, hi + 1e-9, 9)
    hp, _ = np.histogram(p, bins=bins)
    hq, _ = np.histogram(q, bins=bins)
    hp = (hp + eps) / (hp.sum() + eps * len(hp))
    hq = (hq + eps) / (hq.sum() + eps * len(hq))
    return float(np.sum(hp * np.log(hp / hq)))


def closed_loop_calibrate(measured: Sequence[float], regenerate, iterations: int = 3,
                          kl_target: float = 0.1, bins: Optional[Sequence[float]] = None,
                          quantiles: Sequence[float] = tuple(np.linspace(0.05, 0.95, 10))) -> dict:
    """Iteratively correct simulator RT60 targets until the regenerated blind
    estimates match the measured distribution (REQ-302).

    Args:
        measured: blind RT60 estimates of the real (or proxy-real) sessions.
        regenerate: callable(targets: list[float]) -> list[float] — renders scenes
            with these target RT60s and returns blind estimates of the renders.

    Each iteration maps targets by the per-quantile ratio measured_q / regenerated_q
    (the estimator and the renderer may each be biased; the loop cancels both).
    """
    meas = np.asarray([m for m in measured if m], float)
    if bins is None:
        bins = np.linspace(0.0, max(2.0, float(meas.max()) * 1.5), 11)
    targets = np.array(meas, float)
    history = []
    for it in range(iterations + 1):
        regen = np.asarray([r for r in regenerate(list(targets)) if r], float)
        kl = kl_divergence(meas, regen, bins=bins)
        history.append({"iteration": it, "kl": kl, "regen_median_s": float(np.median(regen)),
                        "target_median_s": float(np.median(targets))})
        if kl <= kl_target or it == iterations:
            break
        qm = np.quantile(meas, quantiles)
        qr = np.quantile(regen, quantiles)
        ratio = np.interp(targets, np.quantile(targets, quantiles), qm / np.maximum(qr, 1e-6))
        targets = np.clip(targets * ratio, 0.05, 4.0)
    return {"targets": [float(t) for t in targets], "history": history, "kl": history[-1]["kl"],
            "converged": history[-1]["kl"] <= kl_target}
