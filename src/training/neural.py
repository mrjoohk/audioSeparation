"""
Neural separation candidate (PyTorch, CPU): BLSTM ratio-mask estimator trained with
utterance-level permutation-invariant SI-SDR (REQ-401, REQ-303).

Input features per frame: log-magnitude of the reference mic and cos/sin of the
inter-mic phase difference to one partner mic, so any array with >= 2 mics can
be used (array-agnostic up to the pair spacing).  Output: one mask per speaker
on the reference-channel STFT; estimates are the masked reference spectra,
i.e. each speaker's reverberant image at the reference mic (design §3.3).

Optional on-the-fly augmentation (training.augment) and random partner-mic
choice make the model robust to devices and array geometry (REQ-303).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch
import torch.nn as nn

from datatools.loader import SceneBundle, load_scene
from training.systems import speech_indices

NFFT = 512
HOP = 128


@dataclass
class NetConfig:
    hidden: int = 256
    layers: int = 2
    n_spk: int = 2
    nfft: int = NFFT
    hop: int = HOP
    dropout: float = 0.1


class MaskNet(nn.Module):
    def __init__(self, cfg: NetConfig):
        super().__init__()
        self.cfg = cfg
        F = cfg.nfft // 2 + 1
        self.norm = nn.LayerNorm(3 * F)
        self.inp = nn.Linear(3 * F, cfg.hidden)
        self.rnn = nn.LSTM(cfg.hidden, cfg.hidden, num_layers=cfg.layers, batch_first=True,
                           bidirectional=True, dropout=cfg.dropout if cfg.layers > 1 else 0.0)
        self.out = nn.Linear(2 * cfg.hidden, cfg.n_spk * F)

    def forward(self, feats: torch.Tensor) -> torch.Tensor:
        """feats [B, N, 3F] → masks [B, S, F, N]."""
        B, N, _ = feats.shape
        h = torch.relu(self.inp(self.norm(feats)))
        h, _ = self.rnn(h)
        m = torch.sigmoid(self.out(h))                       # [B, N, S*F]
        F = self.cfg.nfft // 2 + 1
        return m.view(B, N, self.cfg.n_spk, F).permute(0, 2, 3, 1)


def _stft(x: torch.Tensor, cfg: NetConfig) -> torch.Tensor:
    win = torch.hann_window(cfg.nfft, dtype=x.dtype, device=x.device)
    return torch.stft(x, cfg.nfft, cfg.hop, window=win, return_complex=True, center=True)


def _istft(X: torch.Tensor, cfg: NetConfig, length: int) -> torch.Tensor:
    win = torch.hann_window(cfg.nfft, dtype=torch.float32, device=X.device)
    return torch.istft(X, cfg.nfft, cfg.hop, window=win, center=True, length=length)


def features(ref: torch.Tensor, partner: torch.Tensor, cfg: NetConfig):
    """ref/partner [B, T] → (feats [B, N, 3F], X_ref [B, F, N])."""
    Xr = _stft(ref, cfg)
    Xp = _stft(partner, cfg)
    lm = torch.log(Xr.abs() ** 2 + 1e-8)
    ipd = torch.angle(Xp * torch.conj(Xr))
    f = torch.cat([lm, torch.cos(ipd), torch.sin(ipd)], dim=1)          # [B, 3F, N]
    return f.transpose(1, 2), Xr


def si_sdr_t(est: torch.Tensor, ref: torch.Tensor, eps: float = 1e-8) -> torch.Tensor:
    est = est - est.mean(-1, keepdim=True)
    ref = ref - ref.mean(-1, keepdim=True)
    a = (est * ref).sum(-1, keepdim=True) / ((ref ** 2).sum(-1, keepdim=True) + eps)
    t = a * ref
    return 10 * torch.log10((t ** 2).sum(-1) / (((est - t) ** 2).sum(-1) + eps) + eps)


def pit_loss(est: torch.Tensor, refs: torch.Tensor) -> torch.Tensor:
    """est/refs [B, 2, T]: negative SI-SDR of the better of the two assignments."""
    a = si_sdr_t(est, refs).mean(1)
    b = si_sdr_t(est.flip(1), refs).mean(1)
    return -torch.maximum(a, b).mean()


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _scene_arrays(b: SceneBundle):
    sp = speech_indices(b)
    ref = b.reference_channel
    return b.mixture.astype(np.float32), b.references[sp][:, ref].astype(np.float32), ref


def load_training_set(scenes: Sequence[Tuple[str, Optional[str]]], n_spk: int = 2,
                      channels: Optional[Sequence[int]] = None, level_dbfs: Optional[float] = None):
    """Load training scenes into memory.

    ``channels`` keeps only these microphones (the scene's reference channel must be
    one of them; memory saver for 8-channel real recordings).  ``level_dbfs`` scales
    mixture and references by one gain so the reference channel has this RMS, the
    same level the inference AGC front end produces.
    """
    data = []
    for mpath, fp in scenes:
        b = load_scene(mpath, expected_fingerprint=fp)
        if len(speech_indices(b)) != n_spk or b.mixture.shape[0] < 2:
            continue
        mix, refs, ref = _scene_arrays(b)
        all_refs = b.references.astype(np.float32)[speech_indices(b)]
        if channels is not None:
            ch = list(channels)
            if ref not in ch:
                raise ValueError(f"{mpath}: reference channel {ref} not in {ch}")
            mix, all_refs, ref = mix[ch], all_refs[:, ch], ch.index(ref)
            refs = all_refs[:, ref]
        if level_dbfs is not None:
            rms = float(np.sqrt(np.mean(mix[ref].astype(np.float64) ** 2)))
            if rms > 0:
                g = np.float32(10 ** (level_dbfs / 20.0) / rms)
                mix, refs, all_refs = mix * g, refs * g, all_refs * g
        data.append((np.ascontiguousarray(mix), np.ascontiguousarray(refs), ref, np.ascontiguousarray(all_refs)))
    return data


def domain_sampler(sizes: Sequence[int], weights: Sequence[float]):
    """Index sampler over concatenated domains: domain by weight, then uniform item.

    Returns ``draw(rng, n) -> int array`` of indices into the concatenation.
    """
    w = np.asarray(weights, float)
    if len(sizes) != len(w) or np.any(w < 0) or w.sum() <= 0 or any(n <= 0 for n, x in zip(sizes, w) if x > 0):
        raise ValueError("every weighted domain needs items")
    w = w / w.sum()
    off = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(int)

    def draw(rng, n):
        d = rng.choice(len(w), size=n, p=w)
        return np.array([off[k] + int(rng.integers(0, sizes[k])) for k in d], int)
    return draw


def _item(data, i, seg: int, rng, augment):
    """One training example: (ref-mic segment, partner-mic segment, speaker targets)."""
    from training.augment import augment_scene, sample_params
    mix, refs, r, all_refs = data[i]
    if augment is not None:
        p = sample_params(rng, mix.shape[0], augment)
        mix, aug_refs = augment_scene(mix.astype(np.float64), all_refs.astype(np.float64), 16000, p)
        refs = aug_refs[:, r]
    T = mix.shape[1]
    s = int(rng.integers(0, max(1, T - seg + 1)))
    partner = int(rng.choice([c for c in range(mix.shape[0]) if c != r]))
    x = np.zeros((2, seg), np.float32)
    y = np.zeros((refs.shape[0], seg), np.float32)
    n = min(seg, T - s)
    x[0, :n], x[1, :n] = mix[r, s:s + n], mix[partner, s:s + n]
    y[:, :n] = refs[:, s:s + n]
    return x[0], x[1], y


def _stack(items):
    return tuple(torch.from_numpy(np.stack(z)) for z in zip(*items))


def _batch(data, idx, seg: int, rng, augment, cfg):
    return _stack([_item(data, i, seg, rng, augment) for i in idx])


class _ThreadedBatches:
    """Batches built by a thread pool, ``depth`` steps ahead of the training loop.

    Each step draws from its own generator ``SeedSequence([seed, step])`` spawned per
    example, so the batches do not depend on thread scheduling (reproducible).
    """

    def __init__(self, data, seg, augment, batch, seed, threads, depth=3, draw=None):
        from collections import deque
        from concurrent.futures import ThreadPoolExecutor
        self.data, self.seg, self.augment, self.batch, self.seed = data, seg, augment, batch, seed
        self.draw = draw
        self.ex = ThreadPoolExecutor(threads)
        self.q = deque()
        self.next_step = 1
        self.depth = depth

    def _submit(self):
        ss = np.random.SeedSequence([self.seed, self.next_step])
        kids = ss.spawn(self.batch + 1)
        r0 = np.random.default_rng(kids[0])
        idx = self.draw(r0, self.batch) if self.draw else r0.integers(0, len(self.data), size=self.batch)
        self.q.append([self.ex.submit(_item, self.data, int(i), self.seg, np.random.default_rng(k), self.augment)
                       for i, k in zip(idx, kids[1:])])
        self.next_step += 1

    def get(self):
        while len(self.q) < self.depth:
            self._submit()
        return _stack([f.result() for f in self.q.popleft()])

    def close(self):
        self.ex.shutdown(cancel_futures=True)


def train_net(scenes, out_dir: str, steps: int = 3000, batch: int = 8, seg_s: float = 4.0,
              lr: float = 1e-3, seed: int = 0, augment=None, cfg: Optional[NetConfig] = None,
              data_identity: Optional[dict] = None, log_every: int = 200, device: str = "cpu",
              loader_threads: int = 0, domains: Optional[Sequence[dict]] = None) -> dict:
    """Train the mask net.  ``loader_threads > 0`` builds batches in a thread pool ahead
    of the GPU/CPU step (different but still seed-deterministic batch sampling).

    ``domains`` (REQ-301 mixed-domain training) replaces ``scenes``: a list of
    ``{"name", "scenes", "weight", "channels"?, "level_dbfs"?}``; each batch item
    picks a domain by weight, then a scene of that domain uniformly.
    """
    from training.experiment import write_experiment
    cfg = cfg or NetConfig()
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    draw, domain_info = None, None
    if domains:
        data, sizes = [], []
        for d in domains:
            part = load_training_set(d["scenes"], cfg.n_spk, d.get("channels"), d.get("level_dbfs"))
            data += part
            sizes.append(len(part))
        draw = domain_sampler(sizes, [d["weight"] for d in domains])
        domain_info = [{"name": d["name"], "weight": d["weight"], "n_scenes": n, "channels": d.get("channels"),
                        "level_dbfs": d.get("level_dbfs")} for d, n in zip(domains, sizes)]
    else:
        data = load_training_set(scenes, cfg.n_spk)
    if not data:
        raise ValueError("no 2-speaker multichannel training scenes")
    net = MaskNet(cfg).to(device)
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps)
    seg = int(seg_s * 16000)
    log = []
    t0 = time.time()
    net.train()
    loader = _ThreadedBatches(data, seg, augment, batch, seed, loader_threads, draw=draw) if loader_threads > 0 else None
    for step in range(1, steps + 1):
        if loader is not None:
            b = loader.get()
        else:
            idx = draw(rng, batch) if draw else rng.integers(0, len(data), size=batch)
            b = _batch(data, idx, seg, rng, augment, cfg)
        ref, par, tgt = (t.to(device) for t in b)
        f, Xr = features(ref, par, cfg)
        m = net(f)                                            # [B, S, F, N]
        est = _istft((m * Xr[:, None]).reshape(-1, *Xr.shape[1:]), cfg, seg).view(batch, cfg.n_spk, seg)
        loss = pit_loss(est, tgt)
        opt.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(net.parameters(), 5.0)
        opt.step()
        sched.step()
        if step % log_every == 0 or step == 1:
            log.append({"step": step, "si_sdr_db": float(-loss.detach()), "elapsed_s": time.time() - t0})
    if loader is not None:
        loader.close()
    os.makedirs(out_dir, exist_ok=True)
    buf = io.BytesIO()
    torch.save({"state_dict": {k: v.cpu() for k, v in net.state_dict().items()}, "config": asdict(cfg)}, buf)
    data_bytes = buf.getvalue()
    ckpt = os.path.join(out_dir, "masknet.pt")
    with open(ckpt, "wb") as fh:
        fh.write(data_bytes)
    return write_experiment(
        os.path.join(out_dir, "experiment.json"), kind="train_masknet",
        config={**asdict(cfg), "steps": steps, "batch": batch, "seg_s": seg_s, "lr": lr, "device": device, "loader_threads": loader_threads,
                "augment": augment.__dict__ if augment is not None else None},
        seed=seed, data={**(data_identity or {}), "n_scenes": len(data), "domains": domain_info},
        checkpoint={"path": "masknet.pt", "sha256": hashlib.sha256(data_bytes).hexdigest()},
        metrics={"train_log": log, "train_time_s": time.time() - t0},
    )


def load_net(path: str) -> MaskNet:
    ck = torch.load(path, map_location="cpu", weights_only=False)
    net = MaskNet(NetConfig(**ck["config"]))
    net.load_state_dict(ck["state_dict"])
    net.eval()
    return net


class NeuralSeparator:
    """Separation system: masks on the reference channel, partner = nearest other mic.

    ``input_rms_dbfs`` (optional) is a fixed automatic-gain front end: the
    mixture is scaled so the reference channel has this RMS, and the estimates
    are scaled back (masking is linear, so only the network input level changes).
    """

    def __init__(self, net: MaskNet, name: str = "candidate_net", input_rms_dbfs: Optional[float] = None,
                 adapter=None):
        self.net = net
        self.name = name
        self.input_rms_dbfs = input_rms_dbfs
        self.adapter = adapter          # optional fitted training.adaptation.CoralAdapter (feature level)

    def _input(self, b: SceneBundle):
        ref = b.reference_channel
        if b.mixture.shape[0] < 2:
            raise ValueError("NeuralSeparator needs >= 2 microphones")
        pos = np.array([r["effective_position"] for r in b.manifest["receivers"]], float)
        d = np.linalg.norm(pos - pos[ref], axis=1)
        d[ref] = np.inf
        partner = int(np.argmin(d))
        xin = b.mixture[[ref, partner]].astype(np.float64)
        g = 1.0
        if self.input_rms_dbfs is not None:
            rms = float(np.sqrt(np.mean(xin[0] ** 2)))
            if rms > 0:
                g = 10 ** (self.input_rms_dbfs / 20.0) / rms
        x = torch.from_numpy((xin * g).astype(np.float32))
        f, Xr = features(x[:1], x[1:], self.net.cfg)
        return f, Xr, g, partner

    def bin_features(self, b: SceneBundle) -> np.ndarray:
        """Network input of a scene as per-bin vectors [F, N, 4] (log-mag, cos, sin, bias)."""
        with torch.no_grad():
            f = self._input(b)[0]
        return to_bins(f[0].numpy().astype(np.float64), self.net.cfg)

    def separate(self, b: SceneBundle):
        T = b.mixture.shape[1]
        with torch.no_grad():
            f, Xr, g, partner = self._input(b)
            if self.adapter is not None:
                fb = self.adapter.transform(to_bins(f[0].numpy().astype(np.float64), self.net.cfg))
                f = torch.from_numpy(from_bins(fb).astype(np.float32))[None]
            m = self.net(f)[0]                                  # [S, F, N]
            est = _istft(m * Xr, self.net.cfg, T)
        return est.numpy().astype(np.float64) / g, {"partner_mic": partner, "input_gain_db": 20 * np.log10(g),
                                                    "adapted": self.adapter is not None}


def to_bins(f: np.ndarray, cfg: NetConfig) -> np.ndarray:
    """[N, 3F] network features → [F, N, 4] per-bin vectors with a bias column (CoralAdapter layout)."""
    F = cfg.nfft // 2 + 1
    x = f.reshape(f.shape[0], 3, F).transpose(2, 0, 1)                 # [F, N, 3]
    return np.concatenate([x, np.ones(x.shape[:2] + (1,))], axis=-1)


def from_bins(fb: np.ndarray) -> np.ndarray:
    """Inverse of :func:`to_bins` → [N, 3F]."""
    x = fb[..., :3].transpose(1, 2, 0)                                  # [N, 3, F]
    return x.reshape(x.shape[0], -1)


def fit_feature_coral(sep: "NeuralSeparator", source: Sequence[SceneBundle], target: Sequence[SceneBundle],
                      eps: float = 1e-3):
    """Fit CORAL on the separator's own input features: source = training-domain scenes,
    target = unlabeled target-domain mixtures (only ``mixture`` is read)."""
    from training.adaptation import CoralAdapter
    ad = CoralAdapter(eps=eps)
    for dom, bs in (("source", source), ("target", target)):
        for b in bs:
            ad.accumulate(sep.bin_features(b), dom)
    ad.fit()
    return ad
