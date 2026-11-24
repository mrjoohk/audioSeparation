"""
Separation systems compared on the same scenes (audit F-06: unprocessed /
fixed baseline / candidate).

All systems return K estimates on the reference-channel time grid, where K is
the number of speech sources (oracle count from the manifest; for real
sessions the count comes from the session registry).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from datatools.loader import SceneBundle
from training.dsp import delay_and_sum, directional_feature, istft_c, srp_phat, stft_c
from training.models import RidgeMaskModel, make_features


def speech_indices(b: SceneBundle) -> List[int]:
    roles = b.manifest["labels"].get("roles", {})
    return [i for i, s in enumerate(b.source_ids) if roles.get(s, "speech") == "speech"]


def mic_positions(b: SceneBundle) -> np.ndarray:
    return np.array([r["effective_position"] for r in b.manifest["receivers"]], float)


class Unprocessed:
    name = "unprocessed"

    def separate(self, b: SceneBundle) -> Tuple[np.ndarray, Dict]:
        K = len(speech_indices(b))
        x = b.mixture[b.reference_channel].astype(np.float64)
        return np.tile(x, (K, 1)), {}


class DelaySumBaseline:
    """Fixed (untrained) baseline: SRP-PHAT azimuths + delay-and-sum per speaker."""
    name = "baseline_ds"

    def beams(self, b: SceneBundle):
        K = len(speech_indices(b))
        X = stft_c(b.mixture.astype(np.float64), b.fs)
        ref = b.reference_channel
        az = srp_phat(X, b.fs, mic_positions(b), ref, K)
        ds = [delay_and_sum(X, b.fs, mic_positions(b), ref, a) for a in az]
        return X, ds, az

    def separate(self, b: SceneBundle) -> Tuple[np.ndarray, Dict]:
        X, ds, az = self.beams(b)
        T = b.mixture.shape[1]
        return np.stack([istft_c(d, b.fs, T) for d in ds]), {"doa_deg": az}


class MaskCandidate(DelaySumBaseline):
    """Learned candidate: ratio mask (from beam + mixture features) on the reference channel."""
    name = "candidate_mask"

    def __init__(self, model: RidgeMaskModel, adapter=None, name: str = "candidate_mask"):
        self.model = model
        self.adapter = adapter
        self.name = name

    def separate(self, b: SceneBundle) -> Tuple[np.ndarray, Dict]:
        X, ds, az = self.beams(b)
        ref = b.reference_channel
        x_ref = X[ref]
        df = [directional_feature(X, b.fs, mic_positions(b), ref, a) for a in az]
        T = b.mixture.shape[1]
        outs = []
        for k in range(len(ds)):
            f = make_features(ds, x_ref, k, self.model.config.context, df, self.model.config.normalize)
            if self.adapter is not None:
                f = self.adapter.transform(f)
            m = self.model.predict(f)
            outs.append(istft_c(m * x_ref, b.fs, T))
        return np.stack(outs), {"doa_deg": az}


class OracleReferences:
    """Perfect separation: each speech source's reference signal at the reference
    channel.  Diagnostic upper bound only (needs references), never a candidate."""
    name = "oracle"

    def separate(self, b: SceneBundle) -> Tuple[np.ndarray, Dict]:
        ref = b.reference_channel
        return np.stack([b.references[i, ref].astype(np.float64) for i in speech_indices(b)]), {}
