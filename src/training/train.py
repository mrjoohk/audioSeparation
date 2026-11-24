"""
Train the candidate mask model from a W2 release and write an experiment manifest.

Scenes are taken from the release index (split, scene IDs, expected
fingerprints) and loaded from the render directory; every scene is checked
against its release fingerprint, so a run is tied to an exact data version.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

from datatools.loader import SceneBundle, load_scene
from training.dsp import delay_and_sum, directional_feature, srp_phat, stft_c
from training.experiment import release_identity, write_experiment
from training.models import MaskModelConfig, RidgeMaskModel, irm_target, make_features
from training.systems import mic_positions, speech_indices


def release_scenes(release_dir: str, render_dir: str, split: str) -> List[Tuple[str, str]]:
    """[(manifest_path, expected_fingerprint)] for one split of a release."""
    with open(os.path.join(release_dir, "index.json"), encoding="utf-8") as fh:
        idx = json.load(fh)
    return [(os.path.join(render_dir, e["scene_id"], "scene_manifest.json"), e["fingerprint"])
            for e in idx["scenes"] if e["split"] == split]


def _circ(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def assign_speakers(est_az: Sequence[float], true_az: Sequence[float]) -> List[int]:
    """For each true speaker, the index of its matched beam (Hungarian, circular distance)."""
    cost = np.array([[_circ(e, t) for e in est_az] for t in true_az])
    rows, cols = linear_sum_assignment(cost)
    out = [0] * len(true_az)
    for r, c in zip(rows, cols):
        out[r] = int(c)
    return out


def scene_training_pairs(b: SceneBundle, context: int, normalize: bool = False,
                         augment_params: Optional[dict] = None):
    """Yield (features [F,N,D], irm [F,N]) per speech source of one scene.

    With ``augment_params`` (training.augment) the same linear device/environment
    transform is applied to the mixture and the references first.
    """
    sp = speech_indices(b)
    if not sp:
        return
    mixture, references = b.mixture.astype(np.float64), b.references.astype(np.float64)
    if augment_params is not None:
        from training.augment import augment_scene
        mixture, references = augment_scene(mixture, references, b.fs, augment_params)
    X = stft_c(mixture, b.fs)
    ref = b.reference_channel
    pos = mic_positions(b)
    az = srp_phat(X, b.fs, pos, ref, len(sp))
    ds = [delay_and_sum(X, b.fs, pos, ref, a) for a in az]
    df = [directional_feature(X, b.fs, pos, ref, a) for a in az]
    rec_ref = b.receiver_ids[ref]
    true_az = []
    for i in sp:
        pair = next(p for p in b.manifest["geometry"]["pairs"]
                    if p["source_id"] == b.source_ids[i] and p["receiver_id"] == rec_ref)
        true_az.append(pair["doa_az_deg"] % 360.0)
    match = assign_speakers(az, true_az)
    x_ref = X[ref]
    for j, i in enumerate(sp):
        S = stft_c(references[i, ref], b.fs)
        yield make_features(ds, x_ref, match[j], context, df, normalize), irm_target(S, x_ref)


def train_mask_model(
    scenes: Sequence[Tuple[str, Optional[str]]],
    out_dir: str,
    config: Optional[MaskModelConfig] = None,
    seed: int = 0,
    data: Optional[dict] = None,
    max_scenes: Optional[int] = None,
    augment=None,
    n_augment: int = 1,
) -> dict:
    """Fit the ridge mask model; returns the experiment manifest dict.

    ``augment`` (training.augment.AugmentConfig) adds ``n_augment`` augmented
    copies of every scene to the clean one (REQ-303).
    """
    cfg = config or MaskModelConfig()
    model = RidgeMaskModel(cfg)
    rng = np.random.default_rng(seed)
    order = sorted(scenes)
    if max_scenes is not None and len(order) > max_scenes:
        order = [order[i] for i in sorted(rng.choice(len(order), max_scenes, replace=False))]
    used = []
    for mpath, fp in order:
        b = load_scene(mpath, expected_fingerprint=fp)
        for feats, irm in scene_training_pairs(b, cfg.context, cfg.normalize):
            model.accumulate(feats, irm)
        if augment is not None:
            from training.augment import sample_params
            for _ in range(n_augment):
                p = sample_params(rng, b.mixture.shape[0], augment)
                for feats, irm in scene_training_pairs(b, cfg.context, cfg.normalize, p):
                    model.accumulate(feats, irm)
        used.append(b.scene_id)
    model.finalize()
    os.makedirs(out_dir, exist_ok=True)
    ckpt = os.path.join(out_dir, "mask_model.npz")
    sha = model.save(ckpt)
    return write_experiment(
        os.path.join(out_dir, "experiment.json"), kind="train_mask_model",
        config={**cfg.__dict__, "augment": (augment.__dict__ if augment is not None else None),
                "n_augment": n_augment if augment is not None else 0}, seed=seed,
        data={**(data or {}), "n_scenes": len(used),
              "scene_ids_sha256": hashlib.sha256("\n".join(used).encode()).hexdigest()},
        checkpoint={"path": os.path.basename(ckpt), "sha256": sha, "n_frames": model.n_frames},
    )


def train_from_release(release_dir: str, render_dir: str, out_dir: str, split: str = "train",
                       config: Optional[MaskModelConfig] = None, seed: int = 0,
                       max_scenes: Optional[int] = None, augment=None, n_augment: int = 1) -> dict:
    data = {**release_identity(release_dir), "split": split}
    return train_mask_model(release_scenes(release_dir, render_dir, split), out_dir,
                            config=config, seed=seed, data=data, max_scenes=max_scenes,
                            augment=augment, n_augment=n_augment)


def scene_features(b: SceneBundle, context: int, normalize: bool = False):
    """Unlabeled features of every estimated speaker beam (for domain adaptation)."""
    sp = speech_indices(b)
    if not sp:
        return
    X = stft_c(b.mixture.astype(np.float64), b.fs)
    ref = b.reference_channel
    pos = mic_positions(b)
    az = srp_phat(X, b.fs, pos, ref, len(sp))
    ds = [delay_and_sum(X, b.fs, pos, ref, a) for a in az]
    df = [directional_feature(X, b.fs, pos, ref, a) for a in az]
    for k in range(len(az)):
        yield make_features(ds, X[ref], k, context, df, normalize)


def fit_coral(source_scenes, target_scenes, context: int, normalize: bool = False):
    """CORAL adapter from source features and *unlabeled* target-domain scenes."""
    from training.adaptation import CoralAdapter
    ad = CoralAdapter()
    for dom, scenes in (("source", source_scenes), ("target", target_scenes)):
        for mpath, fp in scenes:
            for f in scene_features(load_scene(mpath, expected_fingerprint=fp), context, normalize):
                ad.accumulate(f, dom)
    ad.fit()
    return ad
