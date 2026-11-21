"""End-to-end W1 → loader contract tests (design §3, §7; audit F-01, F-02, F-09)."""
import json
import os

import numpy as np
import pytest
from scipy.io import wavfile

from simulator.if_modules.orchestration import simulate_scene
from simulator.scene_io import UnsupportedProfileError
from simulator.uf.w151_config import SceneConfigValidator
from datatools.loader import load_scene


def _cfg(tmp_path, **over):
    raw = {
        "scene_id": "e2e",
        "seed": 11,
        "room": {"type": "shoebox", "dimensions": {"L": 6.0, "W": 5.0, "H": 3.0}},
        "materials": {"default": "carpet"},
        "sources": [{"source_id": "spk_a", "position": [1.5, 1.6, 1.5]}],
        "receivers": [{"receiver_id": "m0", "position": [3.0, 1.2, 2.5]}],
        "motion": {"duration_s": 1.0},
        "output_dir": str(tmp_path),
    }
    raw.update(over)
    return SceneConfigValidator().validate(raw)


def _two_by_two(tmp_path, **over):
    return _cfg(
        tmp_path,
        scene_id="e2e_2x2",
        sources=[
            {"source_id": "spk_a", "position": [1.5, 1.6, 1.5]},
            {"source_id": "spk_b", "position": [4.5, 1.6, 3.5], "onset_s": 0.25},
        ],
        receivers=[
            {"receiver_id": "m0", "position": [3.0, 1.2, 2.5]},
            {"receiver_id": "m1", "position": [3.2, 1.2, 2.5]},
        ],
        **over,
    )


def test_e2e_1x1_scene(tmp_path):
    res = simulate_scene(_cfg(tmp_path))
    assert res["status"] == "completed"
    assert res["qc"]["passed"], res["qc"]
    b = load_scene(res["manifest_path"], expected_fingerprint=res["fingerprint"])
    assert b.mixture.shape == (1, b.references.shape[-1])
    assert b.references.shape[:2] == (1, 1)
    assert np.all(np.isfinite(b.mixture)) and np.all(np.isfinite(b.references))
    # Direct-path delay in the manifest matches geometry.
    pair = b.manifest["geometry"]["pairs"][0]
    dist = np.linalg.norm(np.array([3.0, 1.2, 2.5]) - np.array([1.5, 1.6, 1.5]))
    assert pair["direct_delay_samples"] == int(round(dist / 343.0 * 16000))


def test_e2e_2x2_scene(tmp_path):
    res = simulate_scene(_two_by_two(tmp_path))
    m = json.load(open(res["manifest_path"], encoding="utf-8"))
    assert m["qc"]["passed"] and all(m["qc"]["checks"].values())
    b = load_scene(res["manifest_path"])
    S, C, T = b.references.shape
    assert (S, C) == (2, 2)
    # Four distinct per-pair references.
    flat = [b.references[s, c] for s in range(S) for c in range(C)]
    for i in range(4):
        for j in range(i + 1, 4):
            assert not np.array_equal(flat[i], flat[j])
    # Before the device chain the mixture is the sum of references: with a
    # noise-free, unit-gain device, mixture - noise == sum(references).
    resid = b.mixture - b.noise - b.references.sum(axis=0)
    assert np.max(np.abs(resid)) <= 1e-5 * max(1.0, float(np.max(np.abs(b.mixture))))
    # Activity labels: spk_b starts 0.25 s later at the reference channel.
    act = m["labels"]["activity"]
    pa = {(p["source_id"], p["receiver_id"]): p for p in m["geometry"]["pairs"]}
    assert act["spk_b"][0] == 4000 + pa[("spk_b", "m0")]["direct_delay_samples"]
    assert 0.0 < m["labels"]["overlap_ratio"] < 1.0
    # Nothing in a reference precedes its declared arrival.
    for (s, r), p in pa.items():
        ref = b.references[b.source_ids.index(s), b.receiver_ids.index(r)]
        assert np.max(np.abs(ref[: p["arrival_start"]])) <= 1e-6 * np.max(np.abs(ref))


def test_wav_files_are_ieee_float32(tmp_path):
    res = simulate_scene(_cfg(tmp_path))
    for name in os.listdir(res["output_dir"]):
        if name.endswith(".wav"):
            fs, data = wavfile.read(os.path.join(res["output_dir"], name))
            assert fs == 16000 and data.dtype == np.float32


def test_config_positions_are_rendered(tmp_path):
    """N-01: configured positions reach the renderer (no random placement)."""
    res = simulate_scene(_cfg(tmp_path))
    m = json.load(open(res["manifest_path"], encoding="utf-8"))
    assert m["receivers"][0]["effective_position"] == [3.0, 1.2, 2.5]
    dist = m["geometry"]["pairs"][0]["distance_m"]
    assert dist == pytest.approx(np.linalg.norm([1.5, -0.4, -1.0]), abs=1e-9)


def test_material_changes_rir(tmp_path):
    """N-02: materials reach the scene state, so they change the RIR."""
    r1 = simulate_scene(_cfg(tmp_path / "a", materials={"default": "concrete"}))
    r2 = simulate_scene(_cfg(tmp_path / "b", materials={"default": "acoustic_tile"}))
    assert r1["acoustic_summary"].rt60_measured_s > r2["acoustic_summary"].rt60_measured_s


def test_per_channel_gain_reaches_mixture(tmp_path):
    cfg = _cfg(tmp_path, receivers=[
        {"receiver_id": "m0", "position": [3.0, 1.2, 2.5]},
        {"receiver_id": "m1", "position": [3.0, 1.2, 2.6], "gain_db": 12.0},
    ])
    b = load_scene(simulate_scene(cfg)["manifest_path"])
    ratio_db = 20 * np.log10(np.std(b.mixture[1]) / np.std(b.mixture[0]))
    assert ratio_db == pytest.approx(12.0, abs=0.5)


def test_array_errors_change_geometry(tmp_path):
    cfg = _two_by_two(tmp_path, impairments={
        "type": "none",
        "array_errors": {"position_sigma_m": 0.01, "max_clock_skew_samples": 3},
    })
    res = simulate_scene(cfg)
    m = json.load(open(res["manifest_path"], encoding="utf-8"))
    assert m["qc"]["passed"]
    recs = m["receivers"]
    assert any(r["nominal_position"] != r["effective_position"] for r in recs)
    shifts = [r["clock_shift_samples"] for r in recs]
    assert all(-3 <= k <= 3 for k in shifts)
    # The direct delay is computed from the *effective* position.
    for p in m["geometry"]["pairs"]:
        r = next(x for x in recs if x["receiver_id"] == p["receiver_id"])
        assert p["distance_m"] == pytest.approx(
            float(np.linalg.norm(np.array(r["effective_position"]) - np.array(
                [1.5, 1.6, 1.5] if p["source_id"] == "spk_a" else [4.5, 1.6, 3.5]))), abs=1e-9)


def test_moving_source_rejected(tmp_path):
    cfg = _cfg(tmp_path, sources=[{
        "source_id": "walker",
        "motion": {"type": "linear", "start": [1, 1.5, 1], "end": [4, 1.5, 3]},
    }])
    with pytest.raises(UnsupportedProfileError):
        simulate_scene(cfg)
    assert not (tmp_path / "e2e").exists()


def test_moving_source_static_approximation_recorded(tmp_path):
    cfg = _cfg(tmp_path, render={"allow_static_approximation": True}, sources=[{
        "source_id": "walker",
        "motion": {"type": "linear", "start": [1, 1.5, 1], "end": [4, 1.5, 3]},
    }])
    m = json.load(open(simulate_scene(cfg)["manifest_path"], encoding="utf-8"))
    assert any("tick 0" in a for a in m["render"]["approximations"])


def test_dry_signal_file_and_onset(tmp_path):
    fs = 16000
    sig = (np.sin(2 * np.pi * 440 * np.arange(8000) / 8000.0) * 0.1).astype(np.float32)
    wav = tmp_path / "speech.wav"
    wavfile.write(str(wav), 8000, sig)  # 8 kHz → resampled to 16 kHz
    cfg = _cfg(tmp_path / "out", sources=[{
        "source_id": "spk_a", "position": [1.5, 1.6, 1.5],
        "signal_path": str(wav), "onset_s": 0.1,
    }])
    res = simulate_scene(cfg)
    m = json.load(open(res["manifest_path"], encoding="utf-8"))
    src = m["sources"][0]
    assert src["kind"] == "file" and src["resampled_from"] == 8000
    assert src["onset_sample"] == 1600 and src["truncated"] is True  # 1 s at 16 kHz > 0.9 s left
    assert src["n_samples"] == fs - 1600
