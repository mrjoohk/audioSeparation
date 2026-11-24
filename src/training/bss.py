"""
Blind source separation by auxiliary-function IVA (AuxIVA, Ono 2011).

Determined case: K sources from M >= K microphones.  For M > K the
observations are reduced per frequency to the K principal components first.
Independent vector analysis couples all frequencies of a source through a
spherical Laplace prior, which solves the frequency permutation problem.
Outputs are *projected back* to the reference microphone, i.e. each estimate
is that source's reverberant image at the reference mic — exactly the
separation target defined in the data contract (design §3.3).

numpy only; no training data required (robust to unseen rooms/arrays by
construction, REQ-303).
"""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

from training.dsp import istft_c, stft_c

NFFT = 2048
HOP = 512


def _pca_reduce(X: np.ndarray, K: int) -> Tuple[np.ndarray, np.ndarray]:
    """X [F, M, N] → (Z [F, K, N], P [F, K, M]) with the K principal components."""
    F, M, N = X.shape
    if K >= M:
        return X, np.broadcast_to(np.eye(M, dtype=complex), (F, M, M)).copy()
    R = np.einsum("fmn,fkn->fmk", X, np.conj(X)) / N
    w, V = np.linalg.eigh(R)                                 # ascending
    Vk = V[:, :, ::-1][:, :, :K]                             # [F, M, K]
    P = np.conj(np.transpose(Vk, (0, 2, 1)))                 # [F, K, M]
    return np.einsum("fkm,fmn->fkn", P, X), P


def auxiva(X: np.ndarray, K: int, n_iter: int = 30, eps: float = 1e-10) -> Tuple[np.ndarray, np.ndarray]:
    """AuxIVA on X [F, M, N].  Returns (Y [F, K, N], W_full [F, K, M]) with Y = W_full X."""
    Z, P = _pca_reduce(X, K)
    F, _, N = Z.shape
    W = np.broadcast_to(np.eye(K, dtype=complex), (F, K, K)).copy()
    Y = Z.copy()
    eye = np.eye(K)
    for _ in range(n_iter):
        r = np.sqrt(np.sum(np.abs(Y) ** 2, axis=0))          # [K, N]
        G = 1.0 / np.maximum(r, eps)
        for k in range(K):
            V = np.einsum("n,fmn,fln->fml", G[k], Z, np.conj(Z)) / N      # [F, K, K]
            WV = np.einsum("fij,fjl->fil", W, V)
            w = np.linalg.solve(WV, np.broadcast_to(eye[:, k], (F, K))[..., None])[..., 0]   # [F, K]
            norm = np.sqrt(np.real(np.einsum("fi,fij,fj->f", np.conj(w), V, w)))
            w = w / np.maximum(norm, eps)[:, None]
            W[:, k, :] = np.conj(w)
        Y = np.einsum("fkm,fmn->fkn", W, Z)
    return Y, np.einsum("fkj,fjm->fkm", W, P)


def projection_back(Y: np.ndarray, W_full: np.ndarray, ref: int) -> np.ndarray:
    """Scale each output to its image at microphone ``ref``: Y_k · A[ref, k], A = pinv(W_full)."""
    A = np.linalg.pinv(W_full)                               # [F, M, K]
    return Y * A[:, ref, :][:, :, None]


class IvaSeparator:
    """Separation system (same interface as training.systems)."""

    def __init__(self, n_iter: int = 30, nfft: int = NFFT, hop: int = HOP, name: str = "candidate_iva"):
        self.n_iter = n_iter
        self.nfft = nfft
        self.hop = hop
        self.name = name

    def separate(self, b) -> Tuple[np.ndarray, Dict]:
        from training.systems import speech_indices
        K = max(1, len(speech_indices(b)))
        x = b.mixture.astype(np.float64)
        T = x.shape[1]
        if x.shape[0] < K:
            return np.tile(x[b.reference_channel], (K, 1)), {"note": "underdetermined: unprocessed"}
        X = stft_c(x, b.fs, nperseg=self.nfft, hop=self.hop)                   # [M, F, N]
        Xf = np.transpose(X, (1, 0, 2))                                       # [F, M, N]
        Y, Wf = auxiva(Xf, K, self.n_iter)
        Yp = projection_back(Y, Wf, b.reference_channel)                      # [F, K, N]
        out = istft_c(np.transpose(Yp, (1, 0, 2)), b.fs, T, nperseg=self.nfft, hop=self.hop)
        return np.asarray(out), {"n_iter": self.n_iter, "nfft": self.nfft}
