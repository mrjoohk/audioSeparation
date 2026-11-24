"""Real-session registry, split assignment, blind guard (audit F-03, F-04)."""
import pytest

from datatools.real_sessions import (
    BlindTestGuard,
    RegistryError,
    assign_session_splits,
    build_session_registry,
    label_availability,
    load_registry,
    validate_rows,
    write_registry,
)
from datatools.splits import LeakageError


def _row(sid, room, speakers, split="", consent="true", **kw):
    r = {
        "session_id": sid, "source": "lab", "license_scope": "internal-research",
        "consent_verified": consent, "room_id": room, "device_id": "dev1",
        "mic_layout": "4ch-circular-5cm", "sync_method": "clap", "device_dsp": "off",
        "speakers": speakers, "has_ref_wave": "true", "has_transcript": "true",
        "has_speaker_timeline": "false", "has_position": "false",
        "annotation_qc_sample": "true", "split": split,
    }
    r.update(kw)
    return r


def _rows():
    return [
        _row("s01", "R1", "A;B"),
        _row("s02", "R1", "C;D"),            # linked to s01 by room
        _row("s03", "R2", "B;E"),            # linked to s01 by speaker B
        _row("s04", "R3", "F;G"),
        _row("s05", "R4", "H;I"),
        _row("s06", "R5", "J;K", has_transcript="false"),
        _row("s07", "R6", "L;M", consent="false"),
    ]


def test_registry_roundtrip(tmp_path):
    rows = validate_rows(_rows())
    p = tmp_path / "real_sessions.csv"
    write_registry(rows, str(p))
    again = load_registry(str(p))
    assert [r["session_id"] for r in again] == [r["session_id"] for r in rows]
    assert again[0]["speakers"] == ["A", "B"] and again[0]["consent_verified"] is True


def test_validation_collects_all_problems():
    bad = _rows()
    bad.append(_row("s01", "R9", "Z"))                         # duplicate
    bad.append(_row("s08", "R9", "Z", device_dsp="maybe"))     # bad enum
    bad.append(_row("s09", "R9", "Z", split="dev", consent="false"))
    with pytest.raises(RegistryError) as ei:
        validate_rows(bad)
    msg = " ".join(ei.value.problems)
    assert "duplicate" in msg and "device_dsp" in msg and "consent_verified is false" in msg


def test_assign_keeps_linked_sessions_together_and_skips_unconsented():
    rows = assign_session_splits(validate_rows(_rows()),
                                 {"train": 0.5, "dev": 0.25, "blind_test": 0.25}, seed=1)
    by = {r["session_id"]: r["split"] for r in rows}
    assert by["s01"] == by["s02"] == by["s03"]
    assert by["s07"] == ""
    reg = build_session_registry(rows)
    assert reg.purpose("s01") == by["s01"]


def test_pre_assigned_conflict_is_leakage():
    rows = validate_rows(_rows())
    rows[0]["split"] = "dev"
    rows[1]["split"] = "blind_test"     # same room as s01
    with pytest.raises(LeakageError):
        assign_session_splits(rows, {"train": 1, "dev": 1, "blind_test": 1})


def test_label_availability_reports_valid_denominator():
    rows = validate_rows(_rows())
    av = label_availability(rows)
    assert av["asr"]["n_with_labels"] == 6 and "s06" in av["asr"]["excluded"]
    assert av["diarization"]["n_with_labels"] == 0


def test_blind_guard():
    rows = assign_session_splits(validate_rows(_rows()),
                                 {"train": 0.4, "dev": 0.3, "blind_test": 0.3}, seed=3)
    g = BlindTestGuard(rows)
    assert isinstance(g.open("dev"), list)
    with pytest.raises(PermissionError):
        g.open("blind_test", checkpoint_sha256="abc")
    g.freeze("abc")
    g.open("blind_test", checkpoint_sha256="abc")
    with pytest.raises(PermissionError):
        g.open("blind_test", checkpoint_sha256="other")
    with pytest.raises(PermissionError):
        g.freeze("other")
    assert [a["purpose"] for a in g.access_log] == ["dev", "blind_test"]
