"""Stage 6 rendering: dynamic_v1 (REQ-W06), band reverb, directivity, binaural (REQ-W05)."""
import json
import math

import numpy as np
import pytest
from scipy import signal

from datatools.loader import load_scene
from evaluation.localization import gcc_phat
from simulator.if_modules.orchestration import simulate_scene
from simulator.uf.w122_reverberation import fit_rt60
from simulator.uf.w124_rir_rendering import octave_band_sos
from simulator.uf.w151_config import SceneConfigValidator

FS = 16000


def _scene(tmp_path, sources, receivers, material="wood", sid="s6", **extra):
    cfg = {"scene_id": sid, "seed": 3,
           "room": {"type": "shoebox", "dimensions": {"L": 8.0, "W": 6.0, "H": 3.0}},
           "materials": {"default": material}, "sources": sources, "receivers": receivers,
           "motion": {"duration_s": 1.0}, "ism_order": 2, "output_dir": str(tmp_path)}
    cfg.update(extra)
    return simulate_scene(SceneConfigValidator().validate(cfg))


# --- REQ-W06 dynamic rendering -------------------------------------------

def test_dynamic_static_equivalence(tmp_path):
    src = [{"source_id": "s0", "position": [2.0, 1.5, 2.0]}]
    rec = [{"receiver_id": "m0", "position": [5.0, 1.2, 4.0]}]
    a = load_scene(_scene(tmp_path / "a", src, rec)["manifest_path"])
    b = load_scene(_scene(tmp_path / "b", src, rec, render={"profile": "dynamic_v1"})["manifest_path"])
    err = a.references - b.references
    rel_db = 10 * np.log10(np.mean(err ** 2) / np.mean(a.references ** 2) + 1e-300)
    assert rel_db < -80.0


def test_dynamic_moving_source_no_clicks_and_traces(tmp_path):
    """1 m/s source, 20 ms ticks, 500 Hz tone: energy above 4 kHz (clicks) < -60 dB."""
    n = FS * 2
    tone = (0.1 * np.sin(2 * np.pi * 500 * np.arange(n) / FS)).astype(np.float32)
    cfg = SceneConfigValidator().validate({
        "scene_id": "mv", "seed": 1,
        "room": {"type": "shoebox", "dimensions": {"L": 8.0, "W": 6.0, "H": 3.0}},
        "materials": {"default": "anechoic"},
        "sources": [{"source_id": "s0", "motion": {"type": "linear", "start": [1.5, 1.5, 2.0], "end": [3.5, 1.5, 2.0]}}],
        "receivers": [{"receiver_id": "m0", "position": [4.0, 1.5, 4.5], "noise_floor_dbfs": -70.0}],
        "motion": {"duration_s": 2.0, "tick_rate_hz": 50.0}, "ism_order": 1,
        "render": {"profile": "dynamic_v1", "fractional_delay": True},
        "output_dir": str(tmp_path),
    })
    res = simulate_scene(cfg, source_signals={"s0": tone})
    m = json.load(open(res["manifest_path"], encoding="utf-8"))
    assert m["qc"]["passed"]
    assert m["geometry"]["dynamic"]["key_rirs"]["s0->m0"] > 10
    trace = m["labels"]["doa_trace"]["s0"]
    assert trace[0][3] != trace[-1][3]              # arrival delay changes over time
    b = load_scene(res["manifest_path"])
    y = b.references[0, 0][4000:28000]              # steady part
    f, P = signal.welch(y, FS, nperseg=2048)
    assert 10 * np.log10(P[f > 4000].sum() / P.sum()) < -60.0


# --- band reverb ---------------------------------------------------------------

def _band_rt60(h, b):
    sos = octave_band_sos(FS)[b]
    return float(fit_rt60(signal.sosfilt(sos, h).astype(np.float32), fs=FS)["rt60_measured_s"])


def test_band_reverb_frequency_dependent_and_causal(tmp_path):
    src = [{"source_id": "s0", "position": [2.0, 1.5, 2.0]}]
    rec = [{"receiver_id": "m0", "position": [5.0, 1.2, 4.0]}]
    res = _scene(tmp_path, src, rec, material="carpet", ism_order=3, render={"band_reverb": True})
    m = json.load(open(res["manifest_path"], encoding="utf-8"))
    assert m["qc"]["passed"]
    from scipy.io import wavfile
    _, h = wavfile.read(f"{res['output_dir']}/rir__s0__m0.wav")
    d = m["geometry"]["pairs"][0]["direct_delay_samples"]
    assert np.all(h[:d] == 0)
    # carpet absorbs 2 % at 125 Hz and 65 % at 4 kHz → much longer low-band decay
    assert _band_rt60(h, 0) > 2.0 * _band_rt60(h, 5)


# --- directivity ---------------------------------------------------------------

def test_cardioid_rejects_rear_source(tmp_path):
    src = [{"source_id": "s0", "position": [4.0, 1.5, 1.0]}]     # at -z of the mics
    front = [{"receiver_id": "m0", "position": [4.0, 1.5, 3.0], "pattern": "cardioid", "yaw_deg": 180.0}]
    back = [{"receiver_id": "m0", "position": [4.0, 1.5, 3.0], "pattern": "cardioid", "yaw_deg": 0.0}]
    a = load_scene(_scene(tmp_path / "f", src, front, material="anechoic")["manifest_path"])
    b = load_scene(_scene(tmp_path / "b", src, back, material="anechoic")["manifest_path"])
    ratio = 10 * np.log10(np.sum(a.references ** 2) / max(np.sum(b.references ** 2), 1e-30))
    assert ratio > 20.0


# --- REQ-W05 binaural ------------------------------------------------------------

def _binaural(tmp_path, src, yaw=0.0, sid="bin"):
    rec = [{"receiver_id": "head", "position": [4.0, 1.5, 3.0], "binaural": True, "yaw_deg": yaw,
            "noise_floor_dbfs": -70.0}]
    return load_scene(_scene(tmp_path, [{"source_id": "s0", "position": src}], rec,
                             material="anechoic", sid=sid)["manifest_path"])


def test_binaural_ild_right_source(tmp_path):
    b = _binaural(tmp_path, [2.0, 1.5, 3.0])                  # right ear side = -x
    assert b.receiver_ids == ["head.L", "head.R"]
    f, Pl = signal.welch(b.references[0, 0], FS, nperseg=1024)
    _, Pr = signal.welch(b.references[0, 1], FS, nperseg=1024)
    band = (f > 1800) & (f < 2200)
    assert 10 * np.log10(Pr[band].sum() / Pl[band].sum()) > 5.0


def test_binaural_itd_front_source(tmp_path):
    b = _binaural(tmp_path, [4.0, 1.5, 5.0])                  # straight ahead (+z)
    tau = gcc_phat(b.references[0, 0], b.references[0, 1], FS, max_tau=0.001)
    assert abs(tau) < 50e-6


def test_binaural_localization_random_yaw(tmp_path):
    """Lateral angle from ITD (Woodworth inverse) over random head orientations: RMS < 5°."""
    rng = np.random.default_rng(0)
    errs = []
    r, c = 0.0875, 343.0
    for i in range(12):
        yaw = float(rng.uniform(-180, 180))
        b = _binaural(tmp_path / str(i), [2.0, 1.5, 3.0], yaw=yaw, sid=f"b{i}")
        itd = gcc_phat(b.references[0, 0], b.references[0, 1], FS, max_tau=0.001)
        grid = np.linspace(-np.pi / 2, np.pi / 2, 3601)
        est = grid[np.argmin(np.abs(r / c * (grid + np.sin(grid)) - itd))]
        d = np.array([2.0, 1.5, 3.0]) - np.array([4.0, 1.5, 3.0])
        y = math.radians(yaw)
        x_l = math.cos(y) * d[0] - math.sin(y) * d[2]
        z_l = math.sin(y) * d[0] + math.cos(y) * d[2]
        az = -math.atan2(x_l, z_l)
        lateral = math.asin(math.sin(az))
        errs.append(math.degrees(est - lateral))
    assert float(np.sqrt(np.mean(np.square(errs)))) < 5.0
