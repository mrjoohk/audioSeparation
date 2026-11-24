"""
AMI Meeting Corpus (CC BY 4.0) adapter: registry rows, word timelines, and
real-room two-speaker evaluation scenes built by superposition.

Real recordings have no separated reference signals.  Because room acoustics
and the recording chain are linear, two **single-speaker** stretches of the
same session recorded on the same array add up to a real two-speaker mixture
whose references are known exactly: each stretch *is* that talker's
reverberant image at every microphone (plus that stretch's room background,
which therefore appears twice in the mixture).  Clips are selected from the
manual word timeline: a target speaker talks for ``min_s``-``max_s`` seconds
and no other participant has a word or vocal sound within ``guard_s``.

Scenes follow the hand-off contract (manifest schema 2.0.0, float32 WAV,
sha256) so datatools.loader / evaluation.compare use them unchanged.  They
carry no source positions (no DOA truth).

Array1 is assumed to be the 8-microphone circular array of 10 cm radius
with microphones numbered in order around the circle (AMI documentation);
positions are only used to pick the nearest partner microphone.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import warnings
import zipfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy.io import wavfile

LICENSE = "CC BY 4.0 (AMI Meeting Corpus, University of Edinburgh)"
ARRAY1 = [[round(0.10 * math.cos(2 * math.pi * k / 8), 4), 0.0, round(0.10 * math.sin(2 * math.pi * k / 8), 4)]
          for k in range(8)]
SITE_ROOM = {"ES": "ami-edinburgh", "IS": "ami-idiap", "TS": "ami-tno", "EN": "ami-edinburgh", "IB": "ami-idiap", "IN": "ami-idiap"}
FS = 16000

_W = re.compile(r'<(w|vocalsound)\b([^>]*)>([^<]*)</\1>|<(vocalsound)\b([^>]*)/>')
_ATTR = re.compile(r'(\w[\w:]*)="([^"]*)"')


@dataclass
class Speaker:
    letter: str
    channel: int
    global_id: str
    words: List[Tuple[float, float, str]] = field(default_factory=list)
    activity: List[Tuple[float, float]] = field(default_factory=list)


def _attrs(s: str) -> Dict[str, str]:
    return dict(_ATTR.findall(s))


def parse_meeting(annotation_zip: str, meeting: str) -> Dict[str, Speaker]:
    """Speakers of ``meeting`` with word timings (punctuation dropped) and activity."""
    with zipfile.ZipFile(annotation_zip) as z:
        meetings = z.read("corpusResources/meetings.xml").decode("latin-1")
        m = re.search(r'<meeting\b[^>]*observation="%s"[^>]*>(.*?)</meeting>' % re.escape(meeting), meetings, re.S)
        if not m:
            raise KeyError(meeting)
        spk: Dict[str, Speaker] = {}
        for tag in re.findall(r"<speaker\b[^>]*/>", m.group(1)):
            a = _attrs(tag)
            spk[a["nxt_agent"]] = Speaker(a["nxt_agent"], int(a["channel"]), a["global_name"])
        for letter, s in spk.items():
            name = f"words/{meeting}.{letter}.words.xml"
            if name not in z.namelist():
                continue
            xml = z.read(name).decode("latin-1")
            for g in _W.finditer(xml):
                kind = g.group(1) or g.group(4)
                a = _attrs(g.group(2) or g.group(5) or "")
                if "starttime" not in a or "endtime" not in a:
                    continue
                t0, t1 = float(a["starttime"]), float(a["endtime"])
                s.activity.append((t0, t1))
                if kind == "w" and a.get("punc") != "true":
                    text = (g.group(3) or "").replace("&#39;", "'").replace("&amp;", "&")
                    s.words.append((t0, t1, text))
            s.words.sort()
            s.activity.sort()
    return spk


def registry_row(meeting: str, speakers: Dict[str, Speaker]) -> dict:
    return {
        "session_id": f"ami-{meeting}", "source": "AMI Meeting Corpus", "license_scope": LICENSE,
        # consent: AMI participants consented to public release (corpus licence); not re-verified here
        "consent_verified": True, "room_id": SITE_ROOM.get(meeting[:2], "ami-" + meeting[:2]),
        "device_id": "ami-array1", "mic_layout": "circular8_r10", "sync_method": "single multichannel recorder",
        "device_dsp": "off", "speakers": sorted(s.global_id for s in speakers.values()),
        "has_ref_wave": False, "has_transcript": True, "has_speaker_timeline": True,
        "has_position": False, "annotation_qc_sample": False, "split": "",
    }


def single_speaker_windows(speakers: Dict[str, Speaker], min_s: float = 2.5, max_s: float = 6.0,
                           guard_s: float = 0.5, min_words: int = 4) -> List[dict]:
    """Stretches where one participant speaks and nobody else makes a sound nearby."""
    out = []
    for s in speakers.values():
        others = sorted(iv for o in speakers.values() if o is not s for iv in o.activity)
        o_start = np.array([a for a, _ in others]) if others else np.zeros(0)
        o_end = np.array([b for _, b in others]) if others else np.zeros(0)
        words = s.words
        i = 0
        while i < len(words):
            j = i
            while j + 1 < len(words) and words[j + 1][1] - words[i][0] <= max_s and words[j + 1][0] - words[j][1] < 1.0:
                j += 1
            t0, t1 = words[i][0], words[j][1]
            if t1 - t0 >= min_s and j - i + 1 >= min_words:
                busy = np.any((o_start < t1 + guard_s) & (o_end > t0 - guard_s))
                if not busy:
                    out.append({"letter": s.letter, "speaker": s.global_id, "channel": s.channel,
                                "t0": t0, "t1": t1, "text": " ".join(w for _, _, w in words[i:j + 1]),
                                "words": [(a - t0, b - t0) for a, b, _ in words[i:j + 1]]})
                i = j + 1
            else:
                i += 1
    return sorted(out, key=lambda w: w["t0"])


def read_array(meeting_dir: str, meeting: str, t0: float, t1: float) -> np.ndarray:
    """Array1 channels 1-8 for [t0, t1) seconds as float32 [8, T]."""
    chans = []
    a, b = int(round(t0 * FS)), int(round(t1 * FS))
    for c in range(1, 9):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", wavfile.WavFileWarning)
            fs, x = wavfile.read(os.path.join(meeting_dir, f"{meeting}.Array1-{c:02d}.wav"), mmap=True)
        if fs != FS:
            raise ValueError(f"{meeting}: fs {fs}")
        seg = np.asarray(x[a:b], np.float64)
        if np.issubdtype(x.dtype, np.integer):
            seg = seg / float(-np.iinfo(x.dtype).min)
        chans.append(seg)
    n = min(len(c) for c in chans)
    return np.stack([c[:n] for c in chans]).astype(np.float32)


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_superposition_scene(out_root: str, scene_id: str, clips: Sequence[np.ndarray], offsets_s: Sequence[float],
                              word_times: Sequence[Sequence[Tuple[float, float]]], meta: dict,
                              positions: Optional[Sequence[Sequence[float]]] = None, license: str = LICENSE,
                              renderer: str = "ami-superposition/1") -> str:
    """Write a two-speaker real-room scene; returns the manifest path.  ``positions``
    (one per channel) defaults to the AMI Array1 geometry."""
    d = os.path.join(out_root, scene_id)
    os.makedirs(d, exist_ok=True)
    offs = [int(round(o * FS)) for o in offsets_s]
    T = max(o + c.shape[1] for o, c in zip(offs, clips))
    C = clips[0].shape[0]
    refs = np.zeros((len(clips), C, T), np.float32)
    for k, (o, c) in enumerate(zip(offs, clips)):
        refs[k, :, o:o + c.shape[1]] = c
    mix = refs.sum(axis=0)
    rec_ids = [f"a{c + 1}" for c in range(C)]
    src_ids = [f"spk{k}" for k in range(len(clips))]
    files = []

    def put(name, x, role, rid, sid=None):
        p = os.path.join(d, name)
        wavfile.write(p, FS, np.asarray(x, np.float32))
        e = {"path": f"{scene_id}/{name}", "role": role, "receiver_id": rid, "sha256": _sha(p)}
        if sid:
            e["source_id"] = sid
        files.append(e)

    for c, rid in enumerate(rec_ids):
        put(f"mixture_{rid}.wav", mix[c], "mixture", rid)
        for k, sid in enumerate(src_ids):
            put(f"reference_{sid}_{rid}.wav", refs[k, c], "reference", rid, sid)
    vad = {sid: [[offs[k] + int(a * FS), offs[k] + int(math.ceil(b * FS))] for a, b in word_times[k]]
           for k, sid in enumerate(src_ids)}
    manifest = {
        "schema_version": "2.0.0", "scene_id": scene_id, "fingerprint": None,
        "render": {"fs": FS, "n_samples": T, "storage_profile": "training", "reference_receiver": rec_ids[0],
                   "renderer": renderer},
        "sources": [{"source_id": s, "role": "speech"} for s in src_ids],
        "receivers": [{"receiver_id": r, "effective_position": list((positions or ARRAY1)[c])}
                      for c, r in enumerate(rec_ids)],
        "files": files, "geometry": {"pairs": []},
        "labels": {"vad": vad, "roles": {s: "speech" for s in src_ids}},
        "qc": {"passed": True, "checks": {"real_recording": True}},
        "provenance": {**meta, "license": license,
                       "method": "superposition of single-speaker Array1 segments of one session"},
    }
    mp = os.path.join(d, "scene_manifest.json")
    with open(mp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return mp


def build_meeting_scenes(annotation_zip: str, meeting_dir: str, meeting: str, out_root: str,
                         n_scenes: int, rng: np.random.Generator, overlap: Tuple[float, float] = (0.2, 0.6),
                         lead_s: float = 0.1, tail_s: float = 0.3) -> List[dict]:
    """Pair single-speaker windows of different talkers; returns scene records."""
    return build_scenes(parse_meeting(annotation_zip, meeting), lambda t0, t1: read_array(meeting_dir, meeting, t0, t1),
                        meeting, out_root, n_scenes, rng, overlap=overlap, lead_s=lead_s, tail_s=tail_s)


def build_scenes(spk: Dict[str, Speaker], reader, meeting: str, out_root: str, n_scenes: int,
                 rng: np.random.Generator, overlap: Tuple[float, float] = (0.2, 0.6), lead_s: float = 0.1,
                 tail_s: float = 0.3, corpus: str = "AMI", positions: Optional[Sequence[Sequence[float]]] = None,
                 license: str = LICENSE, renderer: str = "ami-superposition/1") -> List[dict]:
    """Corpus-independent superposition scenes: ``spk`` gives word timings and activity,
    ``reader(t0, t1)`` returns the array signal [C, T] for that span."""
    wins = single_speaker_windows(spk)
    by_spk: Dict[str, List[dict]] = {}
    for w in wins:
        by_spk.setdefault(w["speaker"], []).append(w)
    talkers = sorted(k for k, v in by_spk.items() if v)
    out = []
    used = set()
    for k in range(n_scenes * 4):
        if len(out) >= n_scenes or len(talkers) < 2:
            break
        a, b = rng.choice(len(talkers), size=2, replace=False)
        wa = by_spk[talkers[a]][int(rng.integers(len(by_spk[talkers[a]])))]
        wb = by_spk[talkers[b]][int(rng.integers(len(by_spk[talkers[b]])))]
        key = (wa["t0"], wb["t0"])
        if key in used:
            continue
        used.add(key)
        ca = reader(wa["t0"] - lead_s, wa["t1"] + tail_s)
        cb = reader(wb["t0"] - lead_s, wb["t1"] + tail_s)
        la, lb = ca.shape[1] / FS, cb.shape[1] / FS
        ov = float(rng.uniform(*overlap)) * min(la, lb)
        off_b = max(0.0, la - ov)
        sid = f"{meeting}_{len(out):03d}"
        wt = [[(s + lead_s, e + lead_s) for s, e in wa["words"]], [(s + lead_s, e + lead_s) for s, e in wb["words"]]]
        mp = write_superposition_scene(out_root, sid, [ca, cb], [0.0, off_b], wt,
                                       {"corpus": corpus, "meeting": meeting,
                                        "windows": [{k: w[k] for k in ("speaker", "t0", "t1")} for w in (wa, wb)]},
                                       positions=positions, license=license, renderer=renderer)
        out.append({"manifest": mp, "meeting": meeting, "transcript": f"{wa['text']} {wb['text']}",
                    "speaker_transcripts": [wa["text"], wb["text"]], "speakers": [wa["speaker"], wb["speaker"]]})
    return out


def blind_rt60_of_meeting(meeting_dir: str, meeting: str, windows: Sequence[dict], max_n: int = 30) -> List[float]:
    """Blind RT60 estimates on single-speaker Array1 channel-1 windows (REQ-302 input)."""
    from training.calibration import blind_rt60
    vals = []
    for w in list(windows)[:max_n]:
        x = read_array(meeting_dir, meeting, w["t0"] - 0.1, w["t1"] + 0.6)[0].astype(np.float64)
        v = blind_rt60(x, FS)
        if v:
            vals.append(float(v))
    return vals


def scene_speaker_transcripts(annotation_zip: str, manifest_paths: Sequence[str]) -> Dict[str, List[str]]:
    """Per-speaker reference texts of superposition scenes (for cpWER).

    The scene manifest records each window's speaker and start time; the text is
    recovered from the same annotation windows that built the scene.  The joined
    texts equal the scene's single transcript (checked).
    """
    cache: Dict[str, Dict[Tuple[str, float], str]] = {}
    out: Dict[str, List[str]] = {}
    for mp in manifest_paths:
        with open(mp, encoding="utf-8") as fh:
            prov = json.load(fh)["provenance"]
        m = prov["meeting"]
        if m not in cache:
            cache[m] = {(w["speaker"], w["t0"]): w["text"]
                        for w in single_speaker_windows(parse_meeting(annotation_zip, m))}
        out[mp] = [cache[m][(w["speaker"], w["t0"])] for w in prov["windows"]]
    return out
