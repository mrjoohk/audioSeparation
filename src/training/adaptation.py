"""
Unsupervised feature-level domain adaptation and domain diagnostics (REQ-304; design §6.3).

* :class:`CoralAdapter` maps target-domain features onto source-domain feature
  statistics (per frequency bin: whitening with the target covariance,
  recolouring with the source covariance).  It needs only *unlabeled* target
  data — the integration point for real recordings without references.
* :func:`domain_bce` fits a logistic domain classifier on held-out halves and
  reports its BCE.  A value near ln 2 ≈ 0.693 means the domains are not
  separable.  Per design §6.3 this is a **diagnostic only**: a constant 0.5
  predictor also scores 0.693, so adoption is decided by dev task gain.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def _sqrtm_psd(C: np.ndarray, inv: bool = False, eps: float = 1e-6) -> np.ndarray:
    w, V = np.linalg.eigh(C)
    w = np.maximum(w, eps)
    d = w ** (-0.5 if inv else 0.5)
    return (V * d) @ V.T


class CoralAdapter:
    """Streaming CORAL: per-bin mean/covariance of source and target features."""

    def __init__(self, eps: float = 1e-3):
        self.eps = eps
        self.A: Optional[np.ndarray] = None    # [F, D, D]
        self.mu_s = None
        self.mu_t = None
        self._acc = {"source": None, "target": None}

    def accumulate(self, feats: np.ndarray, domain: str) -> None:
        if domain not in self._acc:
            raise ValueError(domain)
        x = feats[..., :-1]                     # exclude the bias column
        n = x.shape[1]
        s1 = x.sum(axis=1)
        s2 = np.einsum("fnd,fne->fde", x, x)
        cur = self._acc[domain]
        self._acc[domain] = (n, s1, s2) if cur is None else (cur[0] + n, cur[1] + s1, cur[2] + s2)

    @staticmethod
    def _moments(acc):
        n, s1, s2 = acc
        mu = s1 / n
        C = s2 / n - np.einsum("fd,fe->fde", mu, mu)
        return mu, C

    def fit(self) -> None:
        if self._acc["source"] is None or self._acc["target"] is None:
            raise ValueError("need source and target features")
        self.mu_s, Cs = self._moments(self._acc["source"])
        self.mu_t, Ct = self._moments(self._acc["target"])
        I = np.eye(Cs.shape[-1]) * self.eps
        self.A = np.stack([_sqrtm_psd(Ct[f] + I, inv=True) @ _sqrtm_psd(Cs[f] + I) for f in range(Cs.shape[0])])

    def transform(self, feats: np.ndarray) -> np.ndarray:
        x = feats[..., :-1]
        y = np.einsum("fnd,fde->fne", x - self.mu_t[:, None, :], self.A) + self.mu_s[:, None, :]
        return np.concatenate([y, feats[..., -1:]], axis=-1)


def domain_bce(xs: np.ndarray, xt: np.ndarray, seed: int = 0, iters: int = 300, lr: float = 0.1,
               l2: float = 1e-3) -> float:
    """Held-out BCE of a logistic classifier separating rows of xs (label 0) from xt (label 1)."""
    rng = np.random.default_rng(seed)
    X = np.vstack([xs, xt]).astype(float)
    y = np.concatenate([np.zeros(len(xs)), np.ones(len(xt))])
    idx = rng.permutation(len(X))
    X, y = X[idx], y[idx]
    mu, sd = X.mean(0), X.std(0) + 1e-9
    X = (X - mu) / sd
    half = len(X) // 2
    Xtr, ytr, Xte, yte = X[:half], y[:half], X[half:], y[half:]
    w = np.zeros(X.shape[1])
    b = 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(Xtr @ w + b)))
        g = p - ytr
        w -= lr * (Xtr.T @ g / len(Xtr) + l2 * w)
        b -= lr * g.mean()
    p = np.clip(1 / (1 + np.exp(-(Xte @ w + b))), 1e-7, 1 - 1e-7)
    return float(-np.mean(yte * np.log(p) + (1 - yte) * np.log(1 - p)))
