"""datatools: label alignment, split leakage, evaluator golden values (F-02, F-04, F-05)."""
import math

import numpy as np
import pytest

from datatools.loader import check_label_alignment
from datatools.metrics import (
    join_streams,
    normalize_text,
    permutation_match,
    si_sdr,
    si_sdr_improvement,
    wer,
)
from datatools.splits import (
    BenchmarkIntegrityError,
    LeakageError,
    SessionRegistry,
    assert_no_leakage,
    assign_groups,
    check_split_leakage,
    verify_benchmark_manifest,
)


# --- F-02: 1 ms label alignment boundary at 16 kHz --------------------------

@pytest.mark.parametrize("offset,ok", [(0, True), (15, True), (16, False), (-16, False)])
def test_label_alignment_boundary(offset, ok):
    fs = 16000
    rng = np.random.default_rng(0)
    dry = rng.standard_normal(4000)
    true_delay = 300
    ref = np.concatenate([np.zeros(true_delay), dry])
    passed, lag, err = check_label_alignment(ref, dry, true_delay + offset, fs, tol_ms=1.0)
    assert lag == true_delay
    assert err == abs(offset)
    assert passed is ok


# --- F-04: leakage ------------------------------------------------------------

def _items():
    return [
        {"id": "a", "split": "train", "keys": {"speaker": "spk1", "room": "R1"}},
        {"id": "b", "split": "val", "keys": {"speaker": "spk1", "room": "R2"}},   # train–val leak
        {"id": "c", "split": "test", "keys": {"speaker": "spk3", "room": "R1"}},  # room leak
        {"id": "d", "split": "test", "keys": {"speaker": "spk4", "room": "R3"}},
    ]


def test_split_leakage_detects_train_val_and_room():
    leaks = check_split_leakage(_items())
    found = {(l["key"], l["value"]) for l in leaks}
    assert ("speaker", "spk1") in found  # train–val (missed by REQ-206 as written)
    assert ("room", "R1") in found
    with pytest.raises(LeakageError):
        assert_no_leakage(_items())


def test_split_leakage_clean():
    items = [it for it in _items() if it["id"] in ("a", "d")]
    assert check_split_leakage(items) == []


def test_assign_groups_keeps_connected_assets_together():
    items = [
        {"id": "u1", "keys": {"speaker": "A", "recording": "rec1"}},
        {"id": "u2", "keys": {"speaker": "B", "recording": "rec1"}},  # linked to u1 via rec1
        {"id": "u3", "keys": {"speaker": "B", "room": "R9"}},          # linked to u2 via B
        {"id": "u4", "keys": {"speaker": "C"}},
        {"id": "u5", "keys": {"speaker": "D"}},
    ]
    out = assign_groups(items, {"train": 0.6, "val": 0.2, "test": 0.2}, seed=1)
    assert out["u1"] == out["u2"] == out["u3"]
    labelled = [dict(it, split=out[it["id"]]) for it in items]
    assert check_split_leakage(labelled) == []
    assert out == assign_groups(items, {"train": 0.6, "val": 0.2, "test": 0.2}, seed=1)


def test_session_registered_twice_fails():
    reg = SessionRegistry()
    reg.register("sess_01", "dev")
    reg.register("sess_01", "dev")  # idempotent
    with pytest.raises(LeakageError):
        reg.register("sess_01", "blind_test")


def test_verify_benchmark_manifest(tmp_path):
    import hashlib
    p = tmp_path / "bench.json"
    p.write_text('{"v": 1}', encoding="utf-8")
    good = hashlib.sha256(p.read_bytes()).hexdigest()
    assert verify_benchmark_manifest(str(p), good) == good
    with pytest.raises(BenchmarkIntegrityError):
        verify_benchmark_manifest(str(p), "0" * 64)


# --- F-05: evaluator golden values ---------------------------------------------

def test_si_sdr_golden():
    ref = np.array([1.0, -1.0, 1.0, -1.0])
    noise = 0.1 * np.array([1.0, 1.0, -1.0, -1.0])  # zero-mean, orthogonal to ref
    assert si_sdr(ref + noise, ref) == pytest.approx(20.0, abs=1e-9)
    assert si_sdr(3.0 * (ref + noise), ref) == pytest.approx(20.0, abs=1e-9)  # scale-invariant


def test_si_sdri_needs_mixture():
    ref = np.array([1.0, -1.0, 1.0, -1.0])
    n = np.array([1.0, 1.0, -1.0, -1.0])
    mix = ref + n                    # SI-SDR 0 dB
    est = ref + 0.1 * n              # SI-SDR 20 dB
    assert si_sdr_improvement(est, ref, mix) == pytest.approx(20.0, abs=1e-9)


def test_permutation_swapped_estimates():
    rng = np.random.default_rng(1)
    r = [rng.standard_normal(1000) for _ in range(2)]
    est = [r[1] + 0.01 * rng.standard_normal(1000), r[0] + 0.01 * rng.standard_normal(1000)]
    res = permutation_match(est, r)
    assert [(p[0], p[1]) for p in res["pairs"]] == [(0, 1), (1, 0)]
    assert res["missing_refs"] == [] and res["extra_estimates"] == []


def test_permutation_missing_and_extra_speakers():
    rng = np.random.default_rng(2)
    r = [rng.standard_normal(500) for _ in range(3)]
    one = permutation_match([r[0]], r, missing_score=0.0)
    assert len(one["missing_refs"]) == 2
    full = permutation_match(r, r)
    assert one["mean_score"] < full["mean_score"]  # dropping speakers cannot help
    extra = permutation_match(r + [rng.standard_normal(500)], r)
    assert extra["extra_estimates"] == [3]


def test_wer_golden():
    out = wer("The cat sat on the mat.", "the cat sit on mat")
    assert (out["substitutions"], out["deletions"], out["insertions"]) == (1, 1, 0)
    assert out["wer"] == pytest.approx(2 / 6)
    assert wer("", "")["wer"] == 0.0 and math.isinf(wer("", "x")["wer"])


def test_normalize_and_join_streams():
    assert normalize_text("  Hello,   WORLD! 안녕 ") == "hello world 안녕"
    assert join_streams([(2.0, "world"), (0.5, "hello")]) == "hello world"
