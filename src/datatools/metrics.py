"""
Evaluator core with fixed, documented rules (F-05).

* SI-SDR / SI-SDRi: SI-SDRi is measured against the **mixture on the reference
  channel**, so it needs (estimate, reference, mixture) — not only the first two.
* Speaker permutation: optimal assignment (Hungarian).  Missing speakers
  (references without an estimate) receive ``missing_score``; extra estimates
  are reported, not scored.
* ASR: text normalisation (NFKC, lower case, punctuation removed, whitespace
  collapsed) and WER by token edit distance.  Multiple separated streams are
  joined in start-time order before scoring.

Tool correctness is tested against hand-computed examples
(tests/unit/test_datatools.py); model scores belong to versioned benchmarks.
"""
from __future__ import annotations

import math
import unicodedata
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

EPS = 1e-12


def si_sdr(estimate: np.ndarray, reference: np.ndarray) -> float:
    """Scale-invariant SDR in dB (both signals made zero-mean)."""
    est = np.asarray(estimate, dtype=np.float64).ravel()
    ref = np.asarray(reference, dtype=np.float64).ravel()
    if est.shape != ref.shape:
        raise ValueError(f"shape mismatch {est.shape} vs {ref.shape}")
    est = est - est.mean()
    ref = ref - ref.mean()
    ref_energy = float(np.dot(ref, ref))
    if ref_energy < EPS:
        raise ValueError("reference has no energy")
    alpha = float(np.dot(est, ref)) / ref_energy
    target = alpha * ref
    err = est - target
    return 10.0 * math.log10((float(np.dot(target, target)) + EPS) / (float(np.dot(err, err)) + EPS))


def si_sdr_improvement(estimate: np.ndarray, reference: np.ndarray, mixture: np.ndarray) -> float:
    """SI-SDRi = SI-SDR(estimate) − SI-SDR(mixture), same reference channel."""
    return si_sdr(estimate, reference) - si_sdr(mixture, reference)


def permutation_match(
    estimates: Sequence[np.ndarray],
    references: Sequence[np.ndarray],
    score_fn: Callable[[np.ndarray, np.ndarray], float] = si_sdr,
    missing_score: float = 0.0,
) -> Dict[str, object]:
    """Best one-to-one assignment of estimates to references (maximises total score).

    Returns:
        {"pairs": [(ref_idx, est_idx, score)], "missing_refs": [...],
         "extra_estimates": [...], "mean_score": float}
        ``mean_score`` averages over **references** (missing ones count as
        ``missing_score``), so dropping a speaker cannot raise the score.
    """
    K, N = len(estimates), len(references)
    if N == 0:
        raise ValueError("no references")
    scores = np.full((N, K), -np.inf)
    for n in range(N):
        for k in range(K):
            scores[n, k] = score_fn(estimates[k], references[n])
    pairs: List[Tuple[int, int, float]] = []
    if K > 0:
        rows, cols = linear_sum_assignment(-scores)
        pairs = [(int(r), int(c), float(scores[r, c])) for r, c in zip(rows, cols)]
    matched_refs = {p[0] for p in pairs}
    matched_est = {p[1] for p in pairs}
    missing = [n for n in range(N) if n not in matched_refs]
    extra = [k for k in range(K) if k not in matched_est]
    total = sum(p[2] for p in pairs) + missing_score * len(missing)
    return {"pairs": sorted(pairs), "missing_refs": missing,
            "extra_estimates": extra, "mean_score": total / N}


def normalize_text(text: str) -> str:
    """NFKC, lower-case, drop punctuation/symbols, collapse whitespace."""
    t = unicodedata.normalize("NFKC", text).lower()
    t = "".join(" " if unicodedata.category(ch)[0] in ("P", "S") else ch for ch in t)
    return " ".join(t.split())


def join_streams(segments: Sequence[Tuple[float, str]]) -> str:
    """Join transcripts from several separated streams in start-time order."""
    return " ".join(txt for _, txt in sorted(segments, key=lambda s: s[0]) if txt)


def cp_wer(references: Sequence[str], hypotheses: Sequence[str]) -> Dict[str, float]:
    """Concatenated minimum-permutation WER (cpWER, CHiME-6 / MeetEval).

    Each reference speaker's words are compared with one hypothesis stream's
    words (each stream joined in its own time order); the stream-to-speaker
    assignment with the fewest errors is used.  Unequal counts are padded with
    empty texts, so missing streams count as deletions and extra streams as
    insertions.  ``wer`` = total errors / total reference words.
    """
    import itertools
    refs, hyps = list(references), list(hypotheses)
    k = max(len(refs), len(hyps))
    refs += [""] * (k - len(refs))
    hyps += [""] * (k - len(hyps))
    cost = [[wer(r, h) for h in hyps] for r in refs]
    n_ref = sum(c[0]["n_ref"] for c in cost)
    best, best_perm = None, None
    for perm in itertools.permutations(range(k)):
        e = sum(cost[i][j]["substitutions"] + cost[i][j]["deletions"] + cost[i][j]["insertions"]
                for i, j in enumerate(perm))
        if best is None or e < best:
            best, best_perm = e, perm
    rate = (best / n_ref) if n_ref else (0.0 if best == 0 else math.inf)
    return {"errors": best, "n_ref": n_ref, "wer": rate, "assignment": list(best_perm)}


def wer(reference: str, hypothesis: str, normalize: bool = True) -> Dict[str, float]:
    """Word error rate by token edit distance.

    Returns:
        {"substitutions", "deletions", "insertions", "n_ref", "wer"}.
        With an empty reference, ``wer`` is 0.0 if the hypothesis is empty and
        ``inf`` otherwise (the decision table treats baseline WER 0 separately).
    """
    if normalize:
        reference, hypothesis = normalize_text(reference), normalize_text(hypothesis)
    r, h = reference.split(), hypothesis.split()
    n, m = len(r), len(h)
    # dp[i][j] = (cost, S, D, I)
    dp = [[(0, 0, 0, 0)] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = (i, 0, i, 0)
    for j in range(1, m + 1):
        dp[0][j] = (j, 0, 0, j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if r[i - 1] == h[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
                continue
            sub = dp[i - 1][j - 1]
            dele = dp[i - 1][j]
            ins = dp[i][j - 1]
            dp[i][j] = min(
                (sub[0] + 1, sub[1] + 1, sub[2], sub[3]),
                (dele[0] + 1, dele[1], dele[2] + 1, dele[3]),
                (ins[0] + 1, ins[1], ins[2], ins[3] + 1),
            )
    cost, S, D, I = dp[n][m]
    if n == 0:
        rate = 0.0 if m == 0 else math.inf
    else:
        rate = cost / n
    return {"substitutions": S, "deletions": D, "insertions": I, "n_ref": n, "wer": rate}
