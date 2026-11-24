"""Stage 5 evaluation tools: DER, stream diarizer, ASR plumbing (REQ-402, audit F-05)."""
import json
import sys

import numpy as np
import pytest

from evaluation.asr import CommandAsrBackend, StaticAsrBackend, stream_wer, transcribe_streams
from evaluation.diarization import der, diarize_streams


def test_der_perfect_and_missed():
    ref = {"A": [(0.0, 1.0)], "B": [(1.0, 2.0)]}
    assert der(ref, {"x": [(0.0, 1.0)], "y": [(1.0, 2.0)]}, 2.0)["der"] == 0.0
    d = der(ref, {"x": [(0.0, 1.0)]}, 2.0)
    assert d["missed"] == pytest.approx(0.5) and d["der"] == pytest.approx(0.5)


def test_der_confusion_false_alarm_and_overlap():
    ref = {"A": [(0.0, 2.0)], "B": [(1.0, 2.0)]}         # 1 s overlap, ref speech = 3 s
    hyp = {"x": [(0.0, 2.0)], "y": [(1.0, 3.0)]}         # y adds 1 s false alarm
    d = der(ref, hyp, 3.0)
    assert d["false_alarm"] == pytest.approx(1 / 3)
    assert d["confusion"] == 0.0 and d["missed"] == 0.0
    swapped = der({"A": [(0.0, 1.0)], "B": [(1.0, 2.0)]}, {"x": [(0.0, 2.0)]}, 2.0)
    assert swapped["confusion"] == pytest.approx(0.5)  # one hyp speaker for two refs


def test_der_collar_excludes_boundaries():
    ref = {"A": [(0.0, 1.0)]}
    hyp = {"x": [(0.0, 1.2)]}
    assert der(ref, hyp, 2.0)["der"] > 0
    assert der(ref, hyp, 2.0, collar_s=0.25)["der"] == 0.0


def test_diarize_streams_dominance():
    fs = 16000
    rng = np.random.default_rng(0)
    a = np.zeros(2 * fs)
    b = np.zeros(2 * fs)
    a[:fs] = rng.standard_normal(fs)
    b[fs:] = rng.standard_normal(fs)
    leak = np.stack([a + 0.05 * b, b + 0.05 * a])          # -26 dB leakage
    hyp = diarize_streams(leak, fs)
    d = der({"A": [(0.0, 1.0)], "B": [(1.0, 2.0)]}, hyp, 2.0)
    assert d["der"] < 0.02


def test_asr_streams_joined_in_time_order():
    streams = np.array([np.zeros(10), np.ones(10)])          # distinct (identical streams are deduplicated)
    be = StaticAsrBackend([[(1.0, 1.5, "world")], [(0.2, 0.6, "hello")]])
    assert transcribe_streams(be, streams, 16000) == "hello world"
    be2 = StaticAsrBackend([[(1.0, 1.5, "World!")], [(0.2, 0.6, "hello,")]])
    assert stream_wer(be2, streams, 16000, "Hello world")["wer"] == 0.0


def test_dominance_gate_removes_leaked_words():
    from evaluation.asr import gate_segments, stream_wer_pair
    streams = np.array([np.zeros(10), np.ones(10)])
    # stream 0 holds talker A (0-1 s) and leaks B's words (1-2 s); stream 1 the reverse
    be = StaticAsrBackend([[(0.1, 0.4, "hello"), (1.2, 1.5, "world")],
                           [(0.2, 0.5, "hello"), (1.1, 1.4, "world")]])
    active = {0: [(0.0, 1.0)], 1: [(1.0, 2.0)]}
    plain, gated = stream_wer_pair(be, streams, 16000, "hello world", active)
    assert plain["insertions"] == 2 and gated["wer"] == 0.0
    # a single distinct stream (unprocessed mixture copies) is never gated
    segs = [(0, 0.1, 0.4, "hello"), (0, 5.0, 5.2, "late")]
    assert gate_segments(segs, {0: []}) == segs
    # padding: a midpoint just outside the interval (within 0.1 s) is kept
    two = [(0, 1.02, 1.12, "x"), (1, 3.0, 3.2, "y")]
    assert [t for *_, t in gate_segments(two, {0: [(0.0, 1.0)], 1: [(3.0, 4.0)]})] == ["x", "y"]


def test_word_level_backend_rows_carry_gated_wer(tmp_path):
    from evaluation.compare import summarize
    rows = [{"scene_id": "a", "system": "s", "wer": 0.5, "wer_gated": 0.2},
            {"scene_id": "a", "system": "r", "wer": 0.4, "wer_gated": 0.4}]
    sm = summarize(rows, "s", ["r"])
    assert sm["means"]["s"]["wer_gated"] == 0.2
    assert "s-vs-r:wer_gated" in sm["paired"]


def test_command_asr_backend(tmp_path):
    script = tmp_path / "fake_asr.py"
    script.write_text(
        "import json, sys\n"
        "from scipy.io import wavfile\n"
        "fs, x = wavfile.read(sys.argv[1])\n"
        "print(json.dumps({'start': 0.0, 'end': len(x) / fs, 'text': f'n{len(x)}'}))\n",
        encoding="utf-8",
    )
    be = CommandAsrBackend(f'"{sys.executable}" "{script}" {{wav}}')
    assert be.transcribe(np.zeros(320, np.float32), 16000) == [(0.0, 0.02, "n320")]


def test_separation_metric_rtf():
    """REQ-401 constraint: evaluation faster than real time / 2 (RTF < 0.5)."""
    import time
    from datatools.metrics import permutation_match, si_sdr_improvement
    fs = 16000
    rng = np.random.default_rng(0)
    refs = [rng.standard_normal(60 * fs) for _ in range(2)]
    mix = refs[0] + refs[1]
    est = [refs[1] + 0.1 * rng.standard_normal(60 * fs), refs[0] + 0.1 * rng.standard_normal(60 * fs)]
    t0 = time.perf_counter()
    permutation_match(est, refs, score_fn=lambda e, r: si_sdr_improvement(e, r, mix))
    assert (time.perf_counter() - t0) / 60.0 < 0.5
