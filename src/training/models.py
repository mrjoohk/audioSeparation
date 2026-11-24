"""
Learned ratio-mask model: per-frequency ridge regression on log-power context
features, predicting logit(IRM).  Trained in closed form from streamed
statistics (XᵀX, Xᵀy), so training is deterministic and resumable.

Features for speaker k at (f, t), with ±``context`` frames:
    log10 |DS_k|²,  log10 |X_ref|²,  log10 |DS_k|² − max_{j≠k} log10 |DS_j|²,
    directional feature DF_k (cos of IPD mismatch for speaker k's azimuth)
DS_k is delay-and-sum toward speaker k (identity for single-mic arrays).
"""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import asdict, dataclass
from typing import List, Optional

import numpy as np

EPS = 1e-10


@dataclass
class MaskModelConfig:
    context: int = 2
    ridge: float = 1.0
    irm_clip: float = 0.02
    n_freq: int = 257
    normalize: bool = False      # subtract per-bin median log power (gain/EQ invariance, REQ-303)


def _ctx(feat: np.ndarray, c: int) -> np.ndarray:
    """[F, N] → [F, N, 2c+1] with edge padding along time."""
    pad = np.pad(feat, ((0, 0), (c, c)), mode="edge")
    return np.stack([pad[:, i:i + feat.shape[1]] for i in range(2 * c + 1)], axis=-1)


def make_features(ds: List[np.ndarray], x_ref: np.ndarray, k: int, context: int,
                  df: Optional[List[np.ndarray]] = None, normalize: bool = False) -> np.ndarray:
    """Features [F, N, D] for speaker k (D = 4(2c+1) + 1)."""
    lp = [np.log10(np.abs(d) ** 2 + EPS) for d in ds]
    lx = np.log10(np.abs(x_ref) ** 2 + EPS)
    if normalize:
        ref_level = np.median(lx, axis=1, keepdims=True)
        lp = [l - ref_level for l in lp]
        lx = lx - ref_level
    others = [lp[j] for j in range(len(lp)) if j != k]
    contrast = lp[k] - (np.max(others, axis=0) if others else lp[k])
    F, N = lx.shape
    dfk = df[k] if df is not None else np.zeros((F, N))
    parts = [_ctx(lp[k], context), _ctx(lx, context), _ctx(contrast, context), _ctx(dfk, context),
             np.ones((F, N, 1))]
    return np.concatenate(parts, axis=-1)


def irm_target(s_ref: np.ndarray, x_ref: np.ndarray) -> np.ndarray:
    s = np.abs(s_ref)
    r = np.abs(x_ref - s_ref)
    return s / (s + r + EPS)


class RidgeMaskModel:
    def __init__(self, config: Optional[MaskModelConfig] = None):
        self.config = config or MaskModelConfig()
        self.W: Optional[np.ndarray] = None
        self._xtx: Optional[np.ndarray] = None
        self._xty: Optional[np.ndarray] = None
        self.n_frames = 0

    @property
    def dim(self) -> int:
        return 4 * (2 * self.config.context + 1) + 1

    def accumulate(self, feats: np.ndarray, irm: np.ndarray) -> None:
        c = self.config.irm_clip
        y = np.clip(irm, c, 1 - c)
        y = np.log(y / (1 - y))                                    # logit
        if self._xtx is None:
            F, D = feats.shape[0], feats.shape[-1]
            self._xtx = np.zeros((F, D, D))
            self._xty = np.zeros((F, D))
        self._xtx += np.einsum("fnd,fne->fde", feats, feats)
        self._xty += np.einsum("fnd,fn->fd", feats, y)
        self.n_frames += feats.shape[1]

    def finalize(self) -> None:
        if self._xtx is None:
            raise ValueError("no training data accumulated")
        F, D, _ = self._xtx.shape
        reg = self.config.ridge * np.eye(D)
        reg[-1, -1] = 0.0                                          # no penalty on bias
        self.W = np.stack([np.linalg.solve(self._xtx[f] + reg, self._xty[f]) for f in range(F)])

    def predict(self, feats: np.ndarray) -> np.ndarray:
        z = np.einsum("fnd,fd->fn", feats, self.W)
        return 1.0 / (1.0 + np.exp(-z))

    # --- persistence --------------------------------------------------------
    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        np.savez(buf, W=self.W, config=np.array(json.dumps(asdict(self.config))),
                 n_frames=np.array(self.n_frames))
        return buf.getvalue()

    def save(self, path: str) -> str:
        data = self.to_bytes()
        with open(path, "wb") as fh:
            fh.write(data)
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def load(cls, path: str) -> "RidgeMaskModel":
        with np.load(path) as z:
            m = cls(MaskModelConfig(**json.loads(str(z["config"]))))
            m.W = z["W"]
            m.n_frames = int(z["n_frames"])
        return m
