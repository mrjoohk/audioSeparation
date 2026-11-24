"""
NOTSOFAR-1 meetings (Microsoft, CC BY 4.0) as real-room superposition scenes (design §18).

Each meeting directory holds ``gt_transcription.json`` (utterances with speaker
alias, start/end and per-word timings), ``gt_meeting_metadata.json`` (room,
participants) and one 7-channel circular device ``mc_plaza_0/ch0..ch6.wav``.
Scenes are built by the same corpus-independent builder as AMI
(:func:`datatools.ami.build_scenes`), so the method is unchanged.

Array assumption (pre-registered, §18): ch0 is the centre microphone and
ch1..ch6 lie on a 4.25 cm ring; the public material gives neither radius nor
channel order.
"""
from __future__ import annotations

import json
import math
import os
import re
import warnings
from typing import Dict, List

import numpy as np
from scipy.io import wavfile

from datatools.ami import FS, Speaker, build_scenes

LICENSE = "CC BY 4.0 (NOTSOFAR-1, Microsoft)"
DEVICE = "mc_plaza_0"
N_CH = 7
RING_RADIUS_M = 0.0425
POSITIONS = [[0.0, 0.0, 0.0]] + [[round(RING_RADIUS_M * math.cos(2 * math.pi * k / 6), 5), 0.0,
                                  round(RING_RADIUS_M * math.sin(2 * math.pi * k / 6), 5)] for k in range(6)]
_WORD = re.compile(r"[^\w']+")


def _meta(meeting_dir: str) -> dict:
    with open(os.path.join(meeting_dir, "gt_meeting_metadata.json"), encoding="utf-8") as fh:
        return json.load(fh)


def parse_meeting(meeting_dir: str) -> Dict[str, Speaker]:
    """Speakers with word timings and activity (utterance spans) from ``gt_transcription.json``.

    Speaker ids are ``nsf-<alias>``: NOTSOFAR aliases identify participants
    across meetings.  Words are lower-cased tokens with punctuation removed.
    """
    with open(os.path.join(meeting_dir, "gt_transcription.json"), encoding="utf-8") as fh:
        utts = json.load(fh)
    spk: Dict[str, Speaker] = {}
    for u in utts:
        alias = str(u["speaker_id"])
        s = spk.setdefault(alias, Speaker(alias, -1, f"nsf-{alias}"))
        s.activity.append((float(u["start_time"]), float(u["end_time"])))
        for w in u.get("word_timing") or []:
            text = _WORD.sub("", str(w[0])).strip("'").lower()
            if text:
                s.words.append((float(w[1]), float(w[2]), text))
    for s in spk.values():
        s.words.sort()
        s.activity.sort()
    return spk


def read_array(meeting_dir: str, t0: float, t1: float) -> np.ndarray:
    """``mc_plaza_0`` channels 0-6 for [t0, t1) seconds as float32 [7, T]."""
    chans = []
    a, b = max(0, int(round(t0 * FS))), int(round(t1 * FS))
    for c in range(N_CH):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", wavfile.WavFileWarning)
            fs, x = wavfile.read(os.path.join(meeting_dir, DEVICE, f"ch{c}.wav"), mmap=True)
        if fs != FS:
            raise ValueError(f"{meeting_dir}: fs {fs}")
        seg = np.asarray(x[a:b], np.float64)
        if np.issubdtype(x.dtype, np.integer):
            seg = seg / float(-np.iinfo(x.dtype).min)
        chans.append(seg)
    n = min(len(c) for c in chans)
    return np.stack([c[:n] for c in chans]).astype(np.float32)


def build_meeting_scenes(meeting_dir: str, meeting: str, out_root: str, n_scenes: int,
                         rng: np.random.Generator) -> List[dict]:
    return build_scenes(parse_meeting(meeting_dir), lambda t0, t1: read_array(meeting_dir, t0, t1), meeting,
                        out_root, n_scenes, rng, corpus="NOTSOFAR-1", positions=POSITIONS, license=LICENSE,
                        renderer="notsofar-superposition/1")


def registry_row(meeting_dir: str, meeting: str, split: str = "blind_test") -> dict:
    m = _meta(meeting_dir)
    return {
        "session_id": f"nsf-{meeting}", "source": "NOTSOFAR-1", "license_scope": LICENSE,
        # consent: NOTSOFAR participants consented to public release (corpus licence); not re-verified here
        "consent_verified": True, "room_id": f"nsf-{m['Room']}", "device_id": f"nsf-{DEVICE}",
        "mic_layout": "circular7_center_r4.25_assumed", "sync_method": "single multichannel device",
        "device_dsp": "off", "speakers": sorted(f"nsf-{a}" for a in m["ParticipantAliases"]),
        "has_ref_wave": False, "has_transcript": True, "has_speaker_timeline": True,
        "has_position": False, "annotation_qc_sample": False, "split": split,
    }
