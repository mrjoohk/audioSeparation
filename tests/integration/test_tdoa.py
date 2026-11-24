"""REQ-W03 TDOA verification split into two tests (audit F-09, design §4.3).

(a) Direct-path delay difference between two mics matches geometry (±1 sample).
(b) Direction recovery only under a restricted observation condition: one mic
    pair fixes the cone angle to the pair axis, not a unique 3-D direction.
"""
import json
import math

import numpy as np
import pytest

from datatools.loader import load_scene
from evaluation.localization import (
    cone_angle_deg,
    gcc_phat,
    true_cone_angle_deg,
)
from simulator.if_modules.orchestration import simulate_scene
from simulator.uf.w151_config import SceneConfigValidator

C = 343.0
FS = 16000
MIC0, MIC1 = [3.0, 1.5, 2.5], [3.2, 1.5, 2.5]   # 0.2 m pair along +x


def _render(tmp_path, src, material="acoustic_tile", storage="full", sid="tdoa", fractional=False):
    cfg = SceneConfigValidator().validate({
        "scene_id": sid, "seed": 5,
        "room": {"type": "shoebox", "dimensions": {"L": 7.0, "W": 6.0, "H": 3.0}},
        "materials": {"default": material},
        "sources": [{"source_id": "s0", "position": src}],
        "receivers": [
            {"receiver_id": "m0", "position": MIC0, "noise_floor_dbfs": -70.0},
            {"receiver_id": "m1", "position": MIC1, "noise_floor_dbfs": -70.0},
        ],
        "motion": {"duration_s": 1.0},
        "ism_order": 2,
        "render": {"storage_profile": storage, "fractional_delay": fractional},
        "output_dir": str(tmp_path),
    })
    return simulate_scene(cfg)


@pytest.mark.parametrize("src", [[1.0, 1.5, 1.0], [5.5, 1.5, 4.0], [3.1, 2.4, 5.0]])
def test_direct_delay_difference_matches_geometry(tmp_path, src):
    m = json.load(open(_render(tmp_path, src)["manifest_path"], encoding="utf-8"))
    p = {x["receiver_id"]: x for x in m["geometry"]["pairs"]}
    measured = p["m1"]["direct_delay_samples"] - p["m0"]["direct_delay_samples"]
    exact = (np.linalg.norm(np.subtract(src, MIC1)) - np.linalg.norm(np.subtract(src, MIC0))) / C * FS
    assert abs(measured - exact) <= 1.0


def _random_plane_sources(n, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < n:
        p = [float(rng.uniform(0.5, 6.5)), 1.5, float(rng.uniform(0.5, 5.5))]
        if np.linalg.norm(np.subtract(p, MIC0)) > 1.0:
            out.append(p)
    return out


@pytest.mark.parametrize("src", _random_plane_sources(12))
def test_tdoa_angle_error_below_1deg_anechoic(tmp_path, src):
    """REQ-W03: 2-mic TDOA angular error < 1° at SNR >= 20 dB.

    Needs fractional-delay rendering (integer delays quantise a 0.2 m pair at
    16 kHz to ~9° steps).  The source is in the array plane (restricted
    condition), the error is the cone angle to the pair axis.
    """
    b = load_scene(_render(tmp_path, src, material="anechoic", fractional=True)["manifest_path"])
    tau = gcc_phat(b.mixture[0], b.mixture[1], FS, max_tau=0.2 / C)
    est = cone_angle_deg(tau, 0.2)
    truth = true_cone_angle_deg(src, MIC0, MIC1)
    assert abs(est - truth) < 1.0, (est, truth)


@pytest.mark.parametrize("src", [[1.0, 1.5, 1.0], [5.5, 1.5, 4.0], [3.1, 1.5, 5.0], [1.2, 1.5, 4.8]])
def test_cone_angle_low_reverb_robustness(tmp_path, src):
    """Low-reverb room (acoustic tile), fractional delays: cone angle within 3°."""
    b = load_scene(_render(tmp_path, src, fractional=True)["manifest_path"])
    tau = gcc_phat(b.mixture[0], b.mixture[1], FS, max_tau=0.2 / C)
    assert abs(cone_angle_deg(tau, 0.2) - true_cone_angle_deg(src, MIC0, MIC1)) < 3.0


def test_anechoic_drr_above_40db(tmp_path):
    """REQ-W04: anechoic config (alpha = 1 on all surfaces) → DRR > 40 dB."""
    import json as _j
    m = _j.load(open(_render(tmp_path, [1.0, 1.5, 1.0], material="anechoic")["manifest_path"], encoding="utf-8"))
    assert all(p["drr_db"] > 40.0 for p in m["geometry"]["pairs"])


def test_single_pair_cannot_distinguish_mirror_directions(tmp_path):
    """Sources mirrored about the pair axis (front/back) give the same TDOA."""
    a = load_scene(_render(tmp_path / "a", [1.5, 1.5, 4.0])["manifest_path"])
    b = load_scene(_render(tmp_path / "b", [1.5, 1.5, 1.0])["manifest_path"])
    ta = gcc_phat(a.mixture[0], a.mixture[1], FS, max_tau=0.2 / C)
    tb = gcc_phat(b.mixture[0], b.mixture[1], FS, max_tau=0.2 / C)
    assert abs(ta - tb) <= 2.0 / FS


def test_training_storage_profile(tmp_path):
    res = _render(tmp_path, [1.0, 1.5, 1.0], storage="training")
    m = json.load(open(res["manifest_path"], encoding="utf-8"))
    roles = {f["role"] for f in m["files"]}
    assert roles == {"mixture", "reference", "params", "summary"}
    b = load_scene(res["manifest_path"])
    assert b.noise is None and b.references.shape[:2] == (1, 2)
