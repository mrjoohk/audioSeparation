"""
Importers for public third-party corpora (stage 4 real corpus, stage 6 HRTF).

* LibriSpeech (OpenSLR SLR12, CC BY 4.0): read English speech with transcripts.
  FLAC → 16 kHz float32 WAV, registered as ``speech`` with keys
  ``speaker = ls-<spk>``, ``recording = ls-<spk>-<chapter>`` and the
  transcript in ``meta``.
* DEMAND (Zenodo 1227121, CC BY-SA 3.0): multichannel environment noise.
  One channel per environment is cut into fixed segments and registered as
  ``noise`` with ``noise = demand-<ENV>`` so every segment of one environment
  stays in one split.

Archives are untrusted input: tar members are extracted with the ``data``
filter and zip members are checked for path traversal before extraction.
Downloads themselves are not done here (they need the user's approval).
"""
from __future__ import annotations

import os
import tarfile
import zipfile
from typing import Dict, Iterable, List, Optional

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

from datagen.assets import AssetLibrary

FS = 16000
LIBRISPEECH_LICENSE = "CC BY 4.0 (OpenSLR SLR12)"
DEMAND_LICENSE = "CC BY-SA 3.0 (Zenodo 1227121)"


def safe_extract_tar(path: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(path) as tf:
        tf.extractall(dest, filter="data")


def safe_extract_zip(path: str, dest: str) -> List[str]:
    os.makedirs(dest, exist_ok=True)
    root = os.path.realpath(dest)
    out = []
    with zipfile.ZipFile(path) as zf:
        for m in zf.infolist():
            target = os.path.realpath(os.path.join(dest, m.filename))
            if not target.startswith(root + os.sep) and target != root:
                raise ValueError(f"unsafe zip member {m.filename!r} in {path}")
            zf.extract(m, dest)
            out.append(target)
    return out


def _write_wav(path: str, x: np.ndarray, fs: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wavfile.write(path, fs, np.asarray(x, np.float32))


def _to_fs(x: np.ndarray, fs: int, target: int = FS) -> np.ndarray:
    if fs == target:
        return x
    g = np.gcd(int(fs), int(target))
    return resample_poly(x, target // g, int(fs) // g)


def read_librispeech_transcripts(subset_dir: str) -> Dict[str, str]:
    """{utterance_id: transcript} from every ``*.trans.txt`` below ``subset_dir``."""
    out = {}
    for dirpath, _, files in os.walk(subset_dir):
        for f in files:
            if f.endswith(".trans.txt"):
                with open(os.path.join(dirpath, f), encoding="utf-8") as fh:
                    for line in fh:
                        uid, _, text = line.strip().partition(" ")
                        if uid:
                            out[uid] = text
    return out


def import_librispeech(subset_dir: str, lib: AssetLibrary, subset: str,
                       min_s: float = 0.0, max_s: float = float("inf"),
                       max_per_speaker: Optional[int] = None) -> List[str]:
    """Convert and register a LibriSpeech subset (e.g. ``.../LibriSpeech/dev-clean``).

    WAVs are written below ``<lib.root>/librispeech/<subset>/``.  Returns the asset ids.
    """
    import soundfile as sf
    trans = read_librispeech_transcripts(subset_dir)
    per_spk: Dict[str, int] = {}
    ids = []
    for uid in sorted(trans):
        spk, chap, _ = uid.split("-")
        if max_per_speaker is not None and per_spk.get(spk, 0) >= max_per_speaker:
            continue
        flac = os.path.join(subset_dir, spk, chap, uid + ".flac")
        if not os.path.exists(flac):
            continue
        info = sf.info(flac)
        dur = info.frames / info.samplerate
        if not (min_s <= dur <= max_s):
            continue
        aid = f"ls-{uid}"
        wav = os.path.join(lib.root, "librispeech", subset, uid + ".wav")
        if aid not in lib.assets:
            x, fs = sf.read(flac, dtype="float32")
            _write_wav(wav, _to_fs(x, fs), FS)
            lib.register_wav(wav, "speech", {"speaker": f"ls-{spk}", "recording": f"ls-{spk}-{chap}"},
                             asset_id=aid, meta={"corpus": "LibriSpeech", "subset": subset,
                                                 "license": LIBRISPEECH_LICENSE, "transcript": trans[uid]})
        per_spk[spk] = per_spk.get(spk, 0) + 1
        ids.append(aid)
    return ids


def import_demand(env_dirs: Iterable[str], lib: AssetLibrary, seg_s: float = 30.0,
                  channel: int = 1) -> List[str]:
    """Register DEMAND environments (directories holding ``ch01.wav`` … ``ch16.wav``)."""
    ids = []
    for d in env_dirs:
        env = os.path.basename(os.path.normpath(d))
        fs, raw = wavfile.read(os.path.join(d, f"ch{channel:02d}.wav"))
        x = raw.astype(np.float64)
        if not np.issubdtype(raw.dtype, np.floating):
            x /= float(-np.iinfo(raw.dtype).min)
        x = _to_fs(x, int(fs))
        n = int(seg_s * FS)
        for k in range(len(x) // n):
            aid = f"demand-{env}-{k:02d}"
            if aid not in lib.assets:
                wav = os.path.join(lib.root, "demand", env, f"{aid}.wav")
                _write_wav(wav, x[k * n:(k + 1) * n], FS)
                lib.register_wav(wav, "noise", {"noise": f"demand-{env}"}, asset_id=aid,
                                 meta={"corpus": "DEMAND", "environment": env, "channel": channel,
                                       "license": DEMAND_LICENSE})
            ids.append(aid)
    return ids
