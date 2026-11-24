"""cpWER and the WER-metric diagnosis (design §17)."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from datatools.metrics import cp_wer, join_streams, wer  # noqa: E402
from evaluation.asr import segments_cp_wer  # noqa: E402


def test_cp_wer_picks_best_assignment_and_pads_missing_streams():
    r = cp_wer(["a b c", "d e"], ["d e", "a b c"])
    assert r["wer"] == 0.0 and r["assignment"] == [1, 0]
    one = cp_wer(["a b c", "d e"], ["a b c"])                      # missing stream -> deletions
    assert one["errors"] == 2 and one["n_ref"] == 5
    extra = cp_wer(["a b"], ["a b", "x y z"])                       # extra stream -> insertions
    assert extra["errors"] == 3 and extra["wer"] == pytest.approx(1.5)


def test_time_ordered_join_penalises_perfect_overlapped_streams_but_cpwer_does_not():
    # speaker A "one two three four" and B "five six seven eight" overlap in time
    segs = [(0, 0.0, 0.3, "one"), (0, 0.6, 0.9, "two"), (0, 1.2, 1.5, "three"), (0, 1.8, 2.1, "four"),
            (1, 1.0, 1.3, "five"), (1, 1.4, 1.7, "six"), (1, 1.9, 2.2, "seven"), (1, 2.4, 2.7, "eight")]
    ref = "one two three four five six seven eight"
    joined = wer(ref, join_streams([(s, t) for _, s, _, t in segs]))["wer"]
    assert joined > 0.3                                             # perfect words, interleaved order
    assert segments_cp_wer(segs, ["one two three four", "five six seven eight"], 2)["wer"] == 0.0


def test_oracle_system_returns_reference_signals(tmp_path):
    from datatools.ami import write_superposition_scene
    from datatools.loader import load_scene
    from training.systems import OracleReferences
    rng = np.random.default_rng(3)
    clips = [0.01 * rng.standard_normal((8, 16000)).astype(np.float32) for _ in range(2)]
    mp = write_superposition_scene(str(tmp_path), "s_000", clips, [0.0, 0.5], [[(0.0, 1.0)], [(0.0, 1.0)]], {})
    b = load_scene(mp)
    est, _ = OracleReferences().separate(b)
    np.testing.assert_allclose(est, b.references[:, b.reference_channel])


def test_scene_speaker_transcripts_rebuild_the_scene_text(tmp_path):
    from datatools.ami import build_meeting_scenes, scene_speaker_transcripts
    zp = Path("data/external/ami/ami_public_manual_1.6.2.zip")
    md = Path("data/external/ami/ES2002a")
    if not (ROOT / zp).exists() or not (ROOT / md).exists():
        pytest.skip("AMI annotations or ES2002a audio not available")
    recs = build_meeting_scenes(str(ROOT / zp), str(ROOT / md), "ES2002a", str(tmp_path), 2,
                                np.random.default_rng([7, 2002, 97]))
    spk = scene_speaker_transcripts(str(ROOT / zp), [r["manifest"] for r in recs])
    for r in recs:
        assert len(spk[r["manifest"]]) == 2 and " ".join(spk[r["manifest"]]) == r["transcript"]
