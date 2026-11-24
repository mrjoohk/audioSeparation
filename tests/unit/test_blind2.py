"""Second AMI blind test (design §15 blind2 rules): session-level pairing and the room/speaker guard."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def rr():
    spec = importlib.util.spec_from_file_location("run_real", ROOT / "scripts" / "run_real_data_experiments.py")
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["x"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def test_session_paired_averages_scenes_per_session(rr):
    rows = [{"scene_id": f"S{k}_{i:03d}", "system": s, "si_sdri_db": v}
            for k in range(3) for i in range(2) for s, v in (("c", 1.0 + k + i), ("b", 0.0))]
    r = rr.session_paired(rows, "c", "b", "si_sdri_db")
    assert r["n_sessions"] == 3 and r["mean_diff"] == pytest.approx(2.5)


def test_blind2_list_is_tno_only_and_excludes_used_meeting(rr):
    assert all(m.startswith("TS") for m in rr.BLIND2_MEETINGS)
    assert not any(m.startswith("TS3003") for m in rr.BLIND2_MEETINGS)      # opened once by the v1 candidate


def test_blind2_registry_rejects_room_shared_with_dev(rr, tmp_path, monkeypatch):
    if not rr.AMI_ZIP.exists() or not rr.REGISTRY.exists():
        pytest.skip("AMI annotations not available")
    from datatools.real_sessions import LeakageError
    monkeypatch.setattr(rr, "REGISTRY2", tmp_path / "reg.csv")
    rows = rr.blind2_registry(["TS3007a"])
    assert {r["session_id"]: r["split"] for r in rows}["ami-TS3007a"] == "blind_test"
    with pytest.raises(LeakageError):
        rr.blind2_registry(["TS3007a", "ES2004a"])                          # Edinburgh room is in dev
