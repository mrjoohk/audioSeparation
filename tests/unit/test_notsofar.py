"""NOTSOFAR-1 importer for the blind4 new-site test (design §18)."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from datatools import notsofar  # noqa: E402


def _meeting(tmp_path, dur_s=40.0):
    """Two talkers, each with several clean 4-s stretches far from the other."""
    d = tmp_path / "MTG_99999"
    (d / notsofar.DEVICE).mkdir(parents=True)
    rng = np.random.default_rng(0)
    n = int(dur_s * 16000)
    for c in range(notsofar.N_CH):
        wavfile.write(d / notsofar.DEVICE / f"ch{c}.wav", 16000, (3000 * rng.standard_normal(n)).astype(np.int16))
    utts = []
    for k, t0 in enumerate([1.0, 11.0, 21.0, 31.0]):
        who = "Ann" if k % 2 == 0 else "Bob"
        words = [[f"Word{j}," if j == 0 else f"w{j}", t0 + 0.6 * j, t0 + 0.6 * j + 0.5] for j in range(6)]
        utts.append({"speaker_id": who, "start_time": t0, "end_time": t0 + 3.6, "text": "x", "word_timing": words})
    (d / "gt_transcription.json").write_text(json.dumps(utts), encoding="utf-8")
    (d / "gt_meeting_metadata.json").write_text(json.dumps(
        {"meeting_id": "MTG_99999", "Room": "ROOM_1", "ParticipantAliases": ["Ann", "Bob"]}), encoding="utf-8")
    return d


def test_parse_meeting_words_activity_and_ids(tmp_path):
    spk = notsofar.parse_meeting(str(_meeting(tmp_path)))
    assert set(spk) == {"Ann", "Bob"} and spk["Ann"].global_id == "nsf-Ann"
    assert spk["Ann"].words[0][2] == "word0"                        # punctuation dropped, lower-cased
    assert len(spk["Bob"].activity) == 2 and len(spk["Bob"].words) == 12


def test_scenes_use_seven_channel_assumed_geometry(tmp_path):
    d = _meeting(tmp_path)
    x = notsofar.read_array(str(d), 1.0, 2.0)
    assert x.shape == (7, 16000) and x.dtype == np.float32 and np.abs(x).max() <= 1.0
    recs = notsofar.build_meeting_scenes(str(d), "MTG_99999", str(tmp_path / "sc"), 3, np.random.default_rng([400, 99999]))
    assert recs and all(len(r["speaker_transcripts"]) == 2 for r in recs)
    assert all(" ".join(r["speaker_transcripts"]) == r["transcript"] for r in recs)
    man = json.loads(Path(recs[0]["manifest"]).read_text(encoding="utf-8"))
    pos = np.array([r["effective_position"] for r in man["receivers"]])
    assert len(pos) == 7 and np.allclose(pos[0], 0) and np.allclose(np.linalg.norm(pos[1:], axis=1), 0.0425, atol=1e-5)
    assert man["provenance"]["corpus"] == "NOTSOFAR-1" and "NOTSOFAR" in man["provenance"]["license"]
    from datatools.loader import load_scene
    from training.neural import NeuralSeparator  # noqa: F401  (partner rule: nearest mic)
    b = load_scene(recs[0]["manifest"])
    d0 = np.linalg.norm(pos - pos[b.reference_channel], axis=1)
    d0[b.reference_channel] = np.inf
    assert int(np.argmin(d0)) == 1                                  # pre-registered partner ch1


def test_registry_row_is_blind_and_disjoint_from_ami(tmp_path):
    from datatools.real_sessions import assign_session_splits, validate_rows
    r = notsofar.registry_row(str(_meeting(tmp_path)), "MTG_99999")
    assert r["split"] == "blind_test" and r["room_id"] == "nsf-ROOM_1" and r["speakers"] == ["nsf-Ann", "nsf-Bob"]
    flat = {k: (";".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v) for k, v in r.items()}
    rows = validate_rows([flat])
    assert assign_session_splits(rows, {"dev": 0.5, "blind_test": 0.5})[0]["split"] == "blind_test"


@pytest.fixture(scope="module")
def rr():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_real_b4", ROOT / "scripts" / "run_real_data_experiments.py")
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["x"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def _rows(n_sess, cand_cp, base_cp=0.70, unp_cp=0.84, sdr_gain=3.0, cand_der=0.35, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_sess):
        for k in range(3):
            sid = f"MTG_{32000 + s}_{k:03d}"
            e = lambda: float(rng.normal(0, 0.005))
            rows += [{"scene_id": sid, "system": "unprocessed", "si_sdri_db": 0.0, "der": 0.77, "wer": 0.5, "cpwer": unp_cp + e()},
                     {"scene_id": sid, "system": "v2-base", "si_sdri_db": -0.3, "der": 0.58, "wer": 0.9, "cpwer": base_cp + e()},
                     {"scene_id": sid, "system": "v3-mix", "si_sdri_db": -0.3 + sdr_gain + e(), "der": cand_der,
                      "wer": 0.8, "cpwer": cand_cp + e()}]
    return rows, [f"MTG_{32000 + s}" for s in range(n_sess)]


def test_blind4_verdict_applies_approved_cpwer_rules(rr):
    rows, sess = _rows(24, cand_cp=0.60)
    gate, v, rules = rr.blind4_verdict(rows, sess, "v3-mix", "v2-base")
    assert rules["status"] == "approved"
    assert v["REQ-303"]["verdict"] == "pass" and v["REQ-305"]["verdict"] == "pass"
    assert v["REQ-305"]["metric"] == "cpwer" and v["REQ-402"]["cpwer"]["metric"] == "cpwer"
    assert v["REQ-402"]["verdict"] == "pass"                        # 0.60 vs 0.84 = -28.6 %, DER -42 pp
    rows, sess = _rows(24, cand_cp=0.72, sdr_gain=1.0)              # worse than baseline, small SDR gain
    _, v, _ = rr.blind4_verdict(rows, sess, "v3-mix", "v2-base")
    assert v["REQ-303"]["verdict"] == "fail" and v["REQ-305"]["verdict"] == "fail" and v["REQ-402"]["verdict"] == "fail"
    rows, sess = _rows(12, cand_cp=0.60)                            # fewer than 20 sessions
    _, v, _ = rr.blind4_verdict(rows, sess, "v3-mix", "v2-base")
    assert v["REQ-305"]["verdict"] == "inconclusive" and v["REQ-402"]["verdict"] == "inconclusive"


def test_blind4_result_serialises_rule_amendment_dates(rr, tmp_path, monkeypatch):
    """The approved rules carry YAML dates; the single blind4 run crashed writing them (design 18.2)."""
    rows, sess = _rows(24, cand_cp=0.60)
    monkeypatch.setattr(rr, "BLIND4_OUT", tmp_path)
    rep = {"rows": rows, "summary": {"n_scenes": 72, "means": {}}}
    out = rr.blind4_write_result(rep, sess, "v3-mix", "v2-base", "ab" * 32, ["unprocessed", "v3-mix", "v2-base"])
    back = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert back["verdict"]["REQ-305"]["verdict"] == out["verdict"]["REQ-305"]["verdict"] == "pass"
    assert back["rules_amendments"] and isinstance(back["rules_amendments"][0]["at"], str)


def _sel_rows(spec, n_sess=6, seed=1):
    """spec: system -> (si_sdri_db, cpwer); v2-base is (0, 0.9)."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_sess):
        for k in range(3):
            sid = f"MTG_{30900 + s}_{k:03d}"
            for name, (sdr, cp) in {"v2-base": (0.0, 0.9), **spec}.items():
                rows.append({"scene_id": sid, "system": name, "si_sdri_db": sdr + float(rng.normal(0, 0.01)),
                             "cpwer": cp + float(rng.normal(0, 0.001))})
    return rows


def test_v4_selection_lowest_cpwer_among_candidates_above_baseline(rr):
    rows = _sel_rows({"v4-nsf": (2.0, 0.70), "v4-real": (1.0, 0.65), "v3-real": (-0.5, 0.40), "v3-mix": (0.5, 0.80)})
    best, table = rr.v4_select(rows, ["v4-nsf", "v4-real", "v3-real", "v3-mix"], "v2-base")
    assert best == "v4-real"                                         # v3-real has lower cpWER but is below v2-base
    assert table["v3-real"]["eligible"] is False and table["v4-real"]["n_sessions"] == 6
    best, _ = rr.v4_select(_sel_rows({"v4-nsf": (-1.0, 0.5)}), ["v4-nsf"], "v2-base")
    assert best is None


def test_registry_row_split_parameter(tmp_path):
    r = notsofar.registry_row(str(_meeting(tmp_path)), "MTG_99999", "dev")
    assert r["split"] == "dev"


def test_v4_preregistration_splits_are_disjoint():
    pre = json.loads((ROOT / "reports" / "experiments" / "blind5_notsofar" / "preregistration.json").read_text(encoding="utf-8"))
    tr, dv, b5 = set(pre["train"]["meetings"]), set(pre["selection_dev"]["meetings"]), set(pre["blind5"]["meetings"])
    b4 = set(json.loads((ROOT / "reports" / "experiments" / "blind4_notsofar" / "preregistration.json")
                        .read_text(encoding="utf-8"))["corpus"]["meetings"])
    assert not (tr & dv) and not (tr & b5) and not (dv & b5) and not (b5 & b4)
    assert pre["train"]["excluded"] == ["MTG_30933"] and "MTG_30933" not in tr
    root = ROOT / "data" / "external" / "notsofar_v4"
    if not (root / "eval").exists():
        pytest.skip("NOTSOFAR v4 metadata not on disk")
    meta = lambda part, m: json.loads((root / part / m / "gt_meeting_metadata.json").read_text(encoding="utf-8"))
    seen_rooms = {meta("train", m)["Room"] for m in tr} | {meta("dev1", m)["Room"] for m in dv}
    seen_spk = {a for m in tr for a in meta("train", m)["ParticipantAliases"]} | \
               {a for m in dv for a in meta("dev1", m)["ParticipantAliases"]}
    for m in b5:
        md = meta("eval", m)
        assert md["Room"] in pre["blind5"]["rooms"] and md["Room"] not in seen_rooms
        assert not set(md["ParticipantAliases"]) & seen_spk
