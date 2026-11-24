"""
ASR integration for evaluation (REQ-402, audit F-05).

Rules: every separated stream is transcribed; segments from all streams are
joined in start-time order; text is normalised (datatools.metrics) before WER.

Backends implement ``transcribe(audio, fs) -> [(start_s, end_s, text)]``.
* :class:`CommandAsrBackend` runs an external recogniser (e.g. a local
  whisper.cpp build) that prints JSON lines ``{"start", "end", "text"}``.
* :class:`StaticAsrBackend` returns given segments (tests / cached outputs).
* :class:`WhisperAsrBackend` runs OpenAI Whisper (MIT) in-process on CPU; the
  model file is downloaded separately (``download_root``), never bundled.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from typing import Callable, Dict, List, Mapping, Protocol, Sequence, Tuple

import numpy as np
from scipy.io import wavfile

from datatools.metrics import join_streams, wer

AsrSegment = Tuple[float, float, str]


class AsrBackend(Protocol):
    name: str

    def transcribe(self, audio: np.ndarray, fs: int) -> List[AsrSegment]: ...


class StaticAsrBackend:
    """Returns pre-computed segments per call (in call order)."""

    def __init__(self, outputs: Sequence[List[AsrSegment]], name: str = "static"):
        self._outputs = list(outputs)
        self.name = name
        self.calls = 0

    def transcribe(self, audio: np.ndarray, fs: int) -> List[AsrSegment]:
        out = self._outputs[self.calls] if self.calls < len(self._outputs) else []
        self.calls += 1
        return out


class CommandAsrBackend:
    """External recogniser: ``command`` contains ``{wav}``; stdout = JSON lines."""

    def __init__(self, command: str, name: str = "command", timeout_s: float = 600.0):
        self.command = command
        self.name = name
        self.timeout_s = timeout_s

    def transcribe(self, audio: np.ndarray, fs: int) -> List[AsrSegment]:
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            peak = float(np.max(np.abs(audio))) or 1.0
            wavfile.write(path, fs, (np.asarray(audio, np.float32) / max(1.0, peak)))
            args = [a.replace("{wav}", path) for a in shlex.split(self.command)]
            res = subprocess.run(args, capture_output=True, text=True, timeout=self.timeout_s, check=True)
            segs = []
            for line in res.stdout.splitlines():
                line = line.strip()
                if line:
                    d = json.loads(line)
                    segs.append((float(d["start"]), float(d["end"]), str(d["text"])))
            return segs
        finally:
            os.remove(path)


class WhisperAsrBackend:
    """In-process Whisper recogniser (``pip install openai-whisper``)."""

    def __init__(self, model: str = "small.en", download_root: str = None, device: str = "cpu",
                 name: str = None, language: str = "en", word_level: bool = False):
        self.model_name = model
        self.download_root = download_root
        self.device = device
        self.language = language
        self.word_level = word_level          # one (start, end, word) tuple per word
        self.name = name or f"whisper-{model}" + ("-words" if word_level else "")
        self._model = None

    def _load(self):
        if self._model is None:
            import whisper
            self._model = whisper.load_model(self.model_name, device=self.device,
                                             download_root=self.download_root)
        return self._model

    def transcribe(self, audio: np.ndarray, fs: int) -> List[AsrSegment]:
        x = np.asarray(audio, np.float64)
        if fs != 16000:
            from scipy.signal import resample_poly
            g = np.gcd(int(fs), 16000)
            x = resample_poly(x, 16000 // g, int(fs) // g)
        peak = float(np.max(np.abs(x))) if x.size else 0.0
        if peak <= 0.0:
            return []
        x = (0.9 * x / peak).astype(np.float32)
        r = self._load().transcribe(x, fp16=False, language=self.language,
                                    condition_on_previous_text=False, temperature=0.0,
                                    word_timestamps=self.word_level)
        if self.word_level:
            return [(float(w["start"]), float(w["end"]), str(w["word"]).strip())
                    for s in r["segments"] for w in s.get("words", [])]
        return [(float(s["start"]), float(s["end"]), str(s["text"]).strip()) for s in r["segments"]]


StreamSegment = Tuple[int, float, float, str]          # (stream index, start_s, end_s, text)


def transcribe_stream_segments(backend: AsrBackend, streams: np.ndarray, fs: int) -> List[StreamSegment]:
    """Transcribe each distinct stream; identical streams (e.g. the unprocessed
    system's copies of the mixture) are transcribed once, so duplicated words are
    not counted as insertions."""
    out: List[StreamSegment] = []
    done: List[np.ndarray] = []
    for k, x in enumerate(streams):
        if any(d.shape == x.shape and np.allclose(d, x) for d in done):
            continue
        done.append(np.asarray(x))
        out += [(k, s, e, t) for s, e, t in backend.transcribe(x, fs)]
    return out


GATE_PAD_S = 0.1


def gate_segments(segs: Sequence[StreamSegment], active: Mapping[int, Sequence[Tuple[float, float]]],
                  pad_s: float = GATE_PAD_S) -> List[StreamSegment]:
    """Keep a segment only where its own stream is the active (dominant) talker.

    Separated streams leak the other talker, so each stream's recogniser repeats
    the other talker's words.  ``active[k]`` are stream k's diarized intervals
    (``diarize_streams``: energy VAD with a dominance test).  A segment is kept
    when its midpoint lies inside one of its stream's intervals widened by
    ``pad_s``.  With fewer than two distinct transcribed streams nothing is gated,
    so the single-stream (unprocessed) transcript is unchanged.  Rule fixed before
    evaluation (2026-11-22); intended for word-level segments.
    """
    if len({k for k, *_ in segs}) < 2:
        return list(segs)
    kept = []
    for k, s, e, t in segs:
        mid = 0.5 * (s + e)
        if any(a - pad_s <= mid <= b + pad_s for a, b in active.get(k, ())):
            kept.append((k, s, e, t))
    return kept


def transcribe_streams(backend: AsrBackend, streams: np.ndarray, fs: int) -> str:
    return join_streams([(s, t) for _, s, _, t in transcribe_stream_segments(backend, streams, fs)])


def stream_wer(backend: AsrBackend, streams: np.ndarray, fs: int, reference_text: str) -> Dict[str, float]:
    """WER of the time-ordered join of all stream transcripts."""
    return wer(reference_text, transcribe_streams(backend, streams, fs))


def segments_cp_wer(segs: Sequence[StreamSegment], speaker_texts: Sequence[str], n_streams: int) -> Dict[str, float]:
    """cpWER of stream segments: each stream's words joined in its own time order,
    matched to the per-speaker reference texts with the best assignment."""
    from datatools.metrics import cp_wer
    hyps = [join_streams([(s, t) for k2, s, _, t in segs if k2 == k]) for k in range(n_streams)]
    return cp_wer(list(speaker_texts), hyps)


def stream_wer_pair(backend: AsrBackend, streams: np.ndarray, fs: int, reference_text: str,
                    active: Mapping[int, Sequence[Tuple[float, float]]]) -> Tuple[Dict[str, float], Dict[str, float]]:
    """(plain WER, dominance-gated WER) from one transcription pass."""
    segs = transcribe_stream_segments(backend, streams, fs)
    plain = wer(reference_text, join_streams([(s, t) for _, s, _, t in segs]))
    gated = wer(reference_text, join_streams([(s, t) for _, s, _, t in gate_segments(segs, active)]))
    return plain, gated
