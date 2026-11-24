"""
Compare separation systems on the same scenes (audit F-06; design §6.2).

Per scene and system:
* SI-SDRi (mean over reference speakers, permutation-matched, missing = 0 dB),
  measured on the reference channel against the mixture;
* DER of a stream-based diarizer vs the manifest VAD labels (speech sources);
* azimuth error of the system's DOA estimates (when reported);
* WER when an ASR backend and reference transcripts are given.

Aggregates: mean per system and paired differences (candidate − reference
system per scene) with a paired bootstrap 95 % CI.
"""
from __future__ import annotations

import json
import math
import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from datatools.loader import load_scene
from datatools.metrics import permutation_match, si_sdr_improvement
from evaluation.diarization import der, diarize_streams, samples_to_seconds
from training.systems import speech_indices


def _circ(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def evaluate_scene(manifest_path: str, systems: Sequence, expected_fingerprint: Optional[str] = None,
                   asr=None, transcript: Optional[str] = None,
                   speaker_transcripts: Optional[Sequence[str]] = None) -> List[dict]:
    """``speaker_transcripts`` (one text per speech source, word-level ASR only) adds
    cpWER: per-stream transcripts matched to per-speaker texts (``cpwer``, ``cpwer_gated``)."""
    b = load_scene(manifest_path, expected_fingerprint=expected_fingerprint)
    sp = speech_indices(b)
    ref = b.reference_channel
    mix = b.mixture[ref].astype(np.float64)
    refs = [b.references[i, ref].astype(np.float64) for i in sp]
    rec_ref = b.receiver_ids[ref]
    true_az = []
    for i in sp:   # real recordings may have no source positions (no DOA truth)
        pair = next((p for p in b.manifest.get("geometry", {}).get("pairs", [])
                     if p["source_id"] == b.source_ids[i] and p["receiver_id"] == rec_ref), None)
        if pair is not None and pair.get("doa_az_deg") is not None:
            true_az.append(pair["doa_az_deg"] % 360.0)
    truth_vad = {b.source_ids[i]: samples_to_seconds(b.manifest["labels"]["vad"][b.source_ids[i]], b.fs) for i in sp}
    dur = b.mixture.shape[1] / b.fs
    rows = []
    for sysm in systems:
        est, info = sysm.separate(b)
        pm = permutation_match(list(est), refs, score_fn=lambda e, r: si_sdr_improvement(e, r, mix), missing_score=0.0)
        hyp = diarize_streams(est, b.fs)
        d = der(truth_vad, hyp, dur, collar_s=0.0)
        row = {"scene_id": b.scene_id, "system": sysm.name, "n_speakers": len(sp),
               "n_mics": len(b.receiver_ids), "si_sdri_db": pm["mean_score"], "der": d["der"]}
        if "doa_deg" in info and len(b.receiver_ids) > 1 and len(true_az) == len(sp):
            est_az = info["doa_deg"]
            row["doa_err_deg"] = float(np.mean([min(_circ(e, t) for e in est_az) for t in true_az]))
        if asr is not None and transcript is not None:
            if getattr(asr, "word_level", False):
                from datatools.metrics import join_streams, wer
                from evaluation.asr import gate_segments, segments_cp_wer, transcribe_stream_segments
                active = {int(k[3:]): v for k, v in hyp.items()}          # "hyp<k>" -> stream k
                segs = transcribe_stream_segments(asr, est, b.fs)          # one pass for every WER variant
                gsegs = gate_segments(segs, active)
                row["wer"] = wer(transcript, join_streams([(s, t) for _, s, _, t in segs]))["wer"]
                row["wer_gated"] = wer(transcript, join_streams([(s, t) for _, s, _, t in gsegs]))["wer"]
                if speaker_transcripts is not None:
                    row["cpwer"] = segments_cp_wer(segs, speaker_transcripts, len(est))["wer"]
                    row["cpwer_gated"] = segments_cp_wer(gsegs, speaker_transcripts, len(est))["wer"]
            else:
                from evaluation.asr import stream_wer
                row["wer"] = stream_wer(asr, est, b.fs, transcript)["wer"]
        rows.append(row)
    return rows


def paired_bootstrap(diffs: Sequence[float], n: int = 2000, seed: int = 0,
                     confidence: float = 0.95) -> Tuple[float, float, float]:
    d = np.asarray(diffs, float)
    if len(d) == 0:
        return math.nan, math.nan, math.nan
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, len(d), size=(n, len(d)))].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - confidence) / 2, 1 - (1 - confidence) / 2])
    return float(d.mean()), float(lo), float(hi)


def summarize(rows: Sequence[dict], candidate: str, references: Sequence[str],
              metrics: Sequence[str] = ("si_sdri_db", "der", "doa_err_deg", "wer", "wer_gated",
                                         "cpwer", "cpwer_gated")) -> dict:
    by_sys: Dict[str, Dict[str, dict]] = {}
    for r in rows:
        by_sys.setdefault(r["system"], {})[r["scene_id"]] = r
    means = {s: {m: float(np.mean([r[m] for r in d.values() if m in r]))
                 for m in metrics if any(m in r for r in d.values())} for s, d in by_sys.items()}
    paired = {}
    for refsys in references:
        for m in metrics:
            common = [sid for sid in by_sys.get(candidate, {}) if sid in by_sys.get(refsys, {})
                      and m in by_sys[candidate][sid] and m in by_sys[refsys][sid]]
            if not common:
                continue
            diffs = [by_sys[candidate][sid][m] - by_sys[refsys][sid][m] for sid in common]
            mean, lo, hi = paired_bootstrap(diffs)
            paired[f"{candidate}-vs-{refsys}:{m}"] = {"n": len(common), "mean_diff": mean, "ci95": [lo, hi]}
    return {"means": means, "paired": paired, "n_scenes": len(by_sys.get(candidate, {}))}


def evaluate_systems(scenes: Sequence[Tuple[str, Optional[str]]], systems: Sequence,
                     candidate: str, references: Sequence[str], out_dir: Optional[str] = None,
                     title: str = "System comparison", meta: Optional[dict] = None,
                     asr=None, transcripts: Optional[Mapping[str, str]] = None,
                     speaker_transcripts: Optional[Mapping[str, Sequence[str]]] = None) -> dict:
    """``transcripts`` maps a manifest path to its reference text (WER only where given);
    ``speaker_transcripts`` maps it to per-speaker texts (adds cpWER)."""
    rows: List[dict] = []
    for mpath, fp in scenes:
        text = (transcripts or {}).get(mpath)
        rows += evaluate_scene(mpath, systems, expected_fingerprint=fp,
                               asr=asr if text is not None else None, transcript=text,
                               speaker_transcripts=(speaker_transcripts or {}).get(mpath))
    summary = summarize(rows, candidate, references)
    report = {"meta": meta or {}, "summary": summary, "rows": rows}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "comparison.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        lines = [f"# {title}", "", f"Scenes: {summary['n_scenes']}", "",
                 "| System | SI-SDRi (dB) | DER | DOA error (deg) | WER | WER (gated) |", "| --- | --- | --- | --- | --- | --- |"]
        for s, m in summary["means"].items():
            lines.append(f"| {s} | {m.get('si_sdri_db', float('nan')):.2f} | {m.get('der', float('nan')):.3f} | "
                         f"{m.get('doa_err_deg', float('nan')):.1f} | {m.get('wer', float('nan')):.3f} | "
                         f"{m.get('wer_gated', float('nan')):.3f} |")
        lines += ["", "| Paired difference | n | mean | 95 % CI |", "| --- | --- | --- | --- |"]
        for k, v in summary["paired"].items():
            lines.append(f"| {k} | {v['n']} | {v['mean_diff']:.3f} | [{v['ci95'][0]:.3f}, {v['ci95'][1]:.3f}] |")
        with open(os.path.join(out_dir, "comparison.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return report
