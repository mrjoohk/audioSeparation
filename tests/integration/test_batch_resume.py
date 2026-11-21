"""Checkpoint v2 resume and QC quarantine tests (design §4.4–§4.5; audit F-08)."""
import json
import os
import shutil

import numpy as np
import pytest

from simulator.if_modules.orchestration import simulate_scene
from simulator.scene_io import SceneQCError, verify_scene_output
from simulator.uf.w151_config import SceneConfigValidator
from simulator.uf.w152_batch import JobQueue, run_batch


def _cfg(out, scene_id="job_a", seed=1):
    return SceneConfigValidator().validate({
        "scene_id": scene_id,
        "seed": seed,
        "room": {"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
        "sources": [{"source_id": "s0", "position": [1.0, 1.5, 1.0]}],
        "receivers": [{"receiver_id": "r0", "position": [3.0, 1.5, 2.5]}],
        "motion": {"duration_s": 0.5},
        "ism_order": 1,
        "output_dir": str(out),
    })


def _run(cfgs, out):
    return run_batch(cfgs, worker_count=1, output_dir=str(out),
                     simulate_fn=simulate_scene,
                     checkpoint_file=os.path.join(str(out), "ckpt.json"))


def test_resume_skips_verified(tmp_path):
    cfgs = [_cfg(tmp_path, "job_a"), _cfg(tmp_path, "job_b", seed=2)]
    s1 = _run(cfgs, tmp_path)
    assert (s1.n_completed, s1.n_failed, s1.n_skipped) == (2, 0, 0)
    assert s1.audio_seconds_completed > 0 and s1.bytes_written > 0
    s2 = _run(cfgs, tmp_path)
    assert (s2.n_completed, s2.n_skipped) == (2, 2)


def test_resume_reruns_on_seed_change(tmp_path):
    _run([_cfg(tmp_path, "job_a", seed=1)], tmp_path)
    q = JobQueue([_cfg(tmp_path, "job_a", seed=99)],
                 checkpoint_file=os.path.join(str(tmp_path), "ckpt.json"))
    assert q.pending_count == 1
    assert q.decisions["job_a"] == "rerun:fingerprint_changed"


def test_resume_reruns_on_missing_output(tmp_path):
    cfg = _cfg(tmp_path)
    _run([cfg], tmp_path)
    shutil.rmtree(tmp_path / "job_a")
    q = JobQueue([cfg], checkpoint_file=os.path.join(str(tmp_path), "ckpt.json"))
    assert q.pending_count == 1
    assert q.decisions["job_a"].startswith("rerun:manifest_missing")
    s = _run([cfg], tmp_path)
    assert s.n_skipped == 0 and s.n_completed == 1


def test_resume_reruns_on_corrupted_file(tmp_path):
    cfg = _cfg(tmp_path)
    _run([cfg], tmp_path)
    wav = tmp_path / "job_a" / "mixture__r0.wav"
    data = bytearray(wav.read_bytes())
    data[-4:] = b"\x00\x00\x80\x7f"  # overwrite last sample
    wav.write_bytes(bytes(data))
    ok, why = verify_scene_output(str(tmp_path), "job_a")
    assert not ok and why.startswith("checksum_mismatch")


def test_resume_ignores_legacy_checkpoint_without_output(tmp_path):
    """v1 checkpoint lists the id, but no (verified) output exists → rerun."""
    ckpt = tmp_path / "ckpt.json"
    ckpt.write_text(json.dumps(["job_a"]), encoding="utf-8")
    q = JobQueue([_cfg(tmp_path)], checkpoint_file=str(ckpt))
    assert q.pending_count == 1


def test_display_id_change_keeps_fingerprint(tmp_path):
    a = JobQueue([_cfg(tmp_path, "name_one")])
    b = JobQueue([_cfg(tmp_path / "elsewhere", "name_two")])
    assert a.fingerprint(a._configs[0]) == b.fingerprint(b._configs[0])
    q = JobQueue([_cfg(tmp_path, "name_one"), _cfg(tmp_path, "name_two")])
    assert q.duplicate_groups() == [["name_one", "name_two"]]


def test_failure_reason_recorded(tmp_path):
    bad = _cfg(tmp_path, "job_bad")
    bad.sources[0]["motion"] = {"type": "linear", "start": [1, 1.5, 1], "end": [3, 1.5, 3]}
    s = _run([bad, _cfg(tmp_path, "job_ok")], tmp_path)
    assert s.n_failed == 1 and s.failure_reasons["job_bad"] == "unsupported_profile"
    ck = json.load(open(tmp_path / "ckpt.json", encoding="utf-8"))
    assert ck["schema"] == 2
    assert ck["jobs"]["job_bad"]["status"] == "failed"
    assert ck["jobs"]["job_ok"]["status"] == "completed"


def test_qc_failure_quarantines(tmp_path, monkeypatch):
    """A failing QC check moves the staged scene to _quarantine and leaves no final dir."""
    import simulator.scene_pipeline as sp
    monkeypatch.setattr(sp, "SUM_TOLERANCE_REL", -1.0)  # force component_sum to fail
    with pytest.raises(SceneQCError) as ei:
        simulate_scene(_cfg(tmp_path))
    assert ei.value.check == "component_sum"
    assert not (tmp_path / "job_a").exists()
    q = tmp_path / "_quarantine" / "job_a"
    assert (q / "qc_failure.json").exists()
    assert json.load(open(q / "qc_failure.json", encoding="utf-8"))["check"] == "component_sum"
    assert not (tmp_path / ".staging").exists()


def test_rerender_replaces_previous_output(tmp_path):
    cfg = _cfg(tmp_path)
    r1 = simulate_scene(cfg)
    r2 = simulate_scene(cfg)
    assert r1["output_dir"] == r2["output_dir"]
    ok, _ = verify_scene_output(str(tmp_path), "job_a", expected_fingerprint=r2["fingerprint"])
    assert ok
    assert sorted(os.listdir(tmp_path)) == ["job_a"]
