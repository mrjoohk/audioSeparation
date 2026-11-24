"""
Audio asset library (REQ-202, REQ-206).

Assets are WAV files with identity keys used for leakage-free splitting:
speech → speaker_id + recording_id; noise → noise_id.  Real corpora are added
with :meth:`AssetLibrary.register_wav`.  Because no licensed speech corpus is
available in this repository, :func:`build_synthetic_library` creates
**synthetic stand-ins** (harmonic, formant-filtered, syllable-modulated
"speech-like" signals with pauses, and coloured noises).  They exercise the
pipeline — VAD structure, overlap, SNR — but are not speech; every synthetic
asset is tagged ``"synthetic": true``.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional

import numpy as np
from scipy.io import wavfile
from scipy.signal import lfilter

from datatools.vad import vad_segments


@dataclass
class Asset:
    asset_id: str
    kind: str                      # speech | noise | event
    path: str                      # relative to the library root
    fs: int
    n_samples: int
    sha256: str
    keys: Dict[str, str]           # speaker / recording / noise identifiers
    vad: List[List[int]] = field(default_factory=list)   # active segments (samples)
    synthetic: bool = False
    meta: Dict[str, object] = field(default_factory=dict)


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class AssetLibrary:
    """JSON-indexed asset library rooted at a directory."""

    INDEX = "assets.json"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.assets: Dict[str, Asset] = {}
        idx = os.path.join(self.root, self.INDEX)
        if os.path.exists(idx):
            with open(idx, encoding="utf-8") as fh:
                for a in json.load(fh)["assets"]:
                    self.assets[a["asset_id"]] = Asset(**a)

    def save(self) -> None:
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, self.INDEX), "w", encoding="utf-8") as fh:
            json.dump({"assets": [asdict(a) for a in self.assets.values()]}, fh, indent=1)

    def abspath(self, asset: Asset) -> str:
        return os.path.join(self.root, asset.path)

    def register_wav(self, path: str, kind: str, keys: Dict[str, str],
                     asset_id: Optional[str] = None, synthetic: bool = False,
                     meta: Optional[dict] = None) -> Asset:
        if kind not in ("speech", "noise", "event"):
            raise ValueError(f"kind must be speech|noise|event, got {kind!r}")
        need = {"speech": ("speaker", "recording"), "noise": ("noise",), "event": ("event",)}[kind]
        missing = [k for k in need if not keys.get(k)]
        if missing:
            raise ValueError(f"{kind} asset needs keys {missing}")
        fs, data = wavfile.read(path)
        x = data.astype(np.float64)
        if not np.issubdtype(data.dtype, np.floating):
            x /= float(-np.iinfo(data.dtype).min)
        if x.ndim == 2:
            x = x.mean(axis=1)
        rel = os.path.relpath(os.path.abspath(path), self.root).replace(os.sep, "/")
        aid = asset_id or os.path.splitext(os.path.basename(path))[0]
        a = Asset(
            asset_id=aid, kind=kind, path=rel, fs=int(fs), n_samples=len(x), sha256=_sha(path),
            keys=dict(keys), synthetic=synthetic, meta=dict(meta or {}),
            vad=[list(s) for s in vad_segments(x, fs, min_gap_ms=0.0)] if kind == "speech" else [],
        )
        self.assets[aid] = a
        return a

    def of_kind(self, kind: str, ids: Optional[Iterable[str]] = None) -> List[Asset]:
        pool = self.assets.values() if ids is None else (self.assets[i] for i in ids)
        return [a for a in pool if a.kind == kind]

    def split_items(self) -> List[dict]:
        """Items for datatools.splits (group keys: speaker, recording, noise)."""
        return [{"id": a.asset_id, "keys": dict(a.keys)} for a in self.assets.values()]


# ---------------------------------------------------------------------------
# Synthetic stand-ins
# ---------------------------------------------------------------------------

def synth_speech_like(rng: np.random.Generator, fs: int, duration_s: float, f0: float,
                      formants=(500.0, 1500.0, 2500.0)) -> np.ndarray:
    """Speech-like test signal: voiced syllables (harmonic + formant filter,
    ~4 Hz syllable envelope) separated by pauses.  Not speech."""
    n = int(duration_s * fs)
    t = np.arange(n) / fs
    vib = 1.0 + 0.03 * np.sin(2 * np.pi * rng.uniform(4, 6) * t)
    phase = 2 * np.pi * np.cumsum(f0 * vib) / fs
    src = sum(np.sin(k * phase) / k for k in range(1, 25) if k * f0 < fs / 2 - 200)
    src += 0.05 * rng.standard_normal(n)
    y = src
    for fc in formants:
        r = np.exp(-np.pi * 120.0 / fs)
        a = [1.0, -2 * r * np.cos(2 * np.pi * fc / fs), r * r]
        y = lfilter([1.0 - r], a, y)
    env = np.zeros(n)
    pos = int(rng.uniform(0.05, 0.3) * fs)
    while pos < n:
        syl = int(rng.uniform(0.12, 0.3) * fs)
        w = np.hanning(syl) ** 0.7
        e = min(n, pos + syl)
        env[pos:e] = w[: e - pos]
        pos = e + int(rng.uniform(0.02, 0.08) * fs)
        if rng.random() < 0.18:
            pos += int(rng.uniform(0.25, 0.7) * fs)  # pause between phrases
    y = y * env
    return (0.1 * y / (np.sqrt(np.mean(y[env > 0.1] ** 2)) + 1e-12)).astype(np.float32)


def synth_noise(rng: np.random.Generator, fs: int, duration_s: float, color: str) -> np.ndarray:
    n = int(duration_s * fs)
    w = rng.standard_normal(n)
    if color == "white":
        y = w
    elif color == "pink":
        b = [0.049922035, -0.095993537, 0.050612699, -0.004408786]
        a = [1, -2.494956002, 2.017265875, -0.522189400]
        y = lfilter(b, a, w)
    elif color == "brown":
        y = lfilter([1.0], [1.0, -0.995], w)
    elif color == "hvac":
        y = lfilter([1.0], [1.0, -0.98], w) + 0.3 * np.sin(2 * np.pi * 120 * np.arange(n) / fs)
    else:
        raise ValueError(color)
    return (0.05 * y / (np.std(y) + 1e-12)).astype(np.float32)


def synth_event(rng: np.random.Generator, fs: int, kind: str) -> np.ndarray:
    """Short transient stand-ins: 'knock' (damped low resonance), 'click' (keyboard-like burst train)."""
    if kind == "knock":
        n = int(0.25 * fs)
        t = np.arange(n) / fs
        x = np.sin(2 * np.pi * rng.uniform(120, 220) * t) * np.exp(-t / 0.03)
        x += 0.3 * rng.standard_normal(n) * np.exp(-t / 0.005)
    elif kind == "click":
        n = int(0.6 * fs)
        x = np.zeros(n)
        for _ in range(int(rng.integers(3, 8))):
            p = int(rng.integers(0, n - 200))
            x[p:p + 200] += rng.standard_normal(200) * np.exp(-np.arange(200) / 30.0)
    else:
        raise ValueError(kind)
    return (0.3 * x / (np.max(np.abs(x)) + 1e-12)).astype(np.float32)


def build_synthetic_library(root: str, n_speakers: int = 12, utts_per_speaker: int = 3,
                            n_noises: int = 6, fs: int = 16000, utt_s: float = 4.0,
                            seed: int = 0, n_events: int = 6) -> AssetLibrary:
    """Create a library of synthetic speech-like and noise assets (tagged synthetic)."""
    rng = np.random.default_rng(seed)
    lib = AssetLibrary(root)
    os.makedirs(os.path.join(root, "speech"), exist_ok=True)
    os.makedirs(os.path.join(root, "noise"), exist_ok=True)
    for s in range(n_speakers):
        f0 = float(rng.uniform(95, 240))
        form = tuple(float(rng.uniform(lo, hi)) for lo, hi in ((350, 800), (1000, 2000), (2200, 3200)))
        for u in range(utts_per_speaker):
            x = synth_speech_like(rng, fs, utt_s, f0, form)
            p = os.path.join(root, "speech", f"spk{s:03d}_utt{u}.wav")
            wavfile.write(p, fs, x)
            lib.register_wav(p, "speech", {"speaker": f"spk{s:03d}", "recording": f"spk{s:03d}_rec{u}"},
                             asset_id=f"spk{s:03d}_utt{u}", synthetic=True, meta={"f0": f0})
    colors = ["white", "pink", "brown", "hvac"]
    for k in range(n_noises):
        c = colors[k % len(colors)]
        x = synth_noise(rng, fs, utt_s * 3, c)
        p = os.path.join(root, "noise", f"noise{k:02d}_{c}.wav")
        wavfile.write(p, fs, x)
        lib.register_wav(p, "noise", {"noise": f"noise{k:02d}"}, asset_id=f"noise{k:02d}",
                         synthetic=True, meta={"color": c})
    os.makedirs(os.path.join(root, "event"), exist_ok=True)
    for k in range(n_events):
        ek = ("knock", "click")[k % 2]
        x = synth_event(rng, fs, ek)
        p = os.path.join(root, "event", f"event{k:02d}_{ek}.wav")
        wavfile.write(p, fs, x)
        lib.register_wav(p, "event", {"event": f"event{k:02d}"}, asset_id=f"event{k:02d}",
                         synthetic=True, meta={"type": ek})
    lib.save()
    return lib
