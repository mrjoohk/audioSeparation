"""Real third-party data adapters on tiny synthetic stand-ins (no downloads needed)."""
import math
import os
import tarfile
import zipfile

import numpy as np
import pytest
from scipy import signal
from scipy.io import wavfile

from datagen.assets import AssetLibrary
from datagen.external import import_demand, import_librispeech, safe_extract_tar, safe_extract_zip
from datatools.loader import load_scene

FS = 16000


# --- importers ----------------------------------------------------------------------

def test_import_librispeech_registers_speech_with_transcripts(tmp_path):
    sf = pytest.importorskip("soundfile")
    sub = tmp_path / "LibriSpeech" / "dev-clean"
    for spk, chap in (("84", "121123"), ("174", "50561")):
        d = sub / spk / chap
        d.mkdir(parents=True)
        lines = []
        for k in range(2):
            uid = f"{spk}-{chap}-{k:04d}"
            t = np.arange(int(1.5 * FS)) / FS
            sf.write(str(d / f"{uid}.flac"), 0.3 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 3 * t) > 0), FS)
            lines.append(f"{uid} HELLO WORLD {k}")
        (d / f"{spk}-{chap}.trans.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    lib = AssetLibrary(str(tmp_path / "lib"))
    ids = import_librispeech(str(sub), lib, "dev-clean")
    assert len(ids) == 4
    a = lib.assets["ls-84-121123-0001"]
    assert a.kind == "speech" and a.keys == {"speaker": "ls-84", "recording": "ls-84-121123"}
    assert a.meta["transcript"] == "HELLO WORLD 1" and "CC BY 4.0" in a.meta["license"]
    assert a.vad and a.fs == FS
    fs, x = wavfile.read(lib.abspath(a))
    assert fs == FS and x.dtype == np.float32
    assert import_librispeech(str(sub), lib, "dev-clean", max_s=1.0) == []      # duration filter


def test_import_demand_groups_segments_by_environment(tmp_path):
    env = tmp_path / "OOFFICE"
    env.mkdir()
    wavfile.write(str(env / "ch01.wav"), FS, (np.random.default_rng(0).standard_normal(FS * 7) * 3000).astype(np.int16))
    lib = AssetLibrary(str(tmp_path / "lib"))
    ids = import_demand([str(env)], lib, seg_s=3.0)
    assert ids == ["demand-OOFFICE-00", "demand-OOFFICE-01"]
    assert {lib.assets[i].keys["noise"] for i in ids} == {"demand-OOFFICE"}
    _, x = wavfile.read(lib.abspath(lib.assets[ids[0]]))
    assert x.dtype == np.float32 and np.max(np.abs(x)) < 1.0


def test_archive_extraction_rejects_path_traversal(tmp_path):
    z = tmp_path / "bad.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../evil.txt", "x")
    with pytest.raises(ValueError):
        safe_extract_zip(str(z), str(tmp_path / "out"))
    t = tmp_path / "bad.tar"
    with tarfile.open(t, "w") as tf:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 1
        import io
        tf.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(Exception):
        safe_extract_tar(str(t), str(tmp_path / "out2"))
    assert not (tmp_path / "evil.txt").exists()


# --- measured HRTF (SOFA) -----------------------------------------------------------

def _fake_sofa(path, fs=48000):
    h5py = pytest.importorskip("h5py")
    az = np.arange(0, 360, 5.0)
    pos = np.stack([az, np.zeros_like(az), np.full_like(az, 1.5)], axis=1)
    ir = np.zeros((len(az), 2, 256))
    for m, a in enumerate(np.radians(az)):          # SOFA azimuth: positive = left
        s = math.sin(a)
        ir[m, 0, 60 - int(round(15 * s))] = 1.0 + 0.6 * s
        ir[m, 1, 60 + int(round(15 * s))] = 1.0 - 0.6 * s
    with h5py.File(path, "w") as f:
        f["Data.IR"] = ir
        f["SourcePosition"] = pos
        f["Data.SamplingRate"] = np.array([float(fs)])
    return str(path)


def test_sofa_loader_centres_and_orients(tmp_path):
    from simulator.hrtf_db import load_sofa
    db = load_sofa(_fake_sofa(tmp_path / "s.sofa"))
    front, left = db.nearest(np.array([0, 0, 1.0])), db.nearest(np.array([1.0, 0, 0]))
    assert abs(int(np.argmax(np.abs(db.left[front]))) - 64) <= 1
    assert np.argmax(np.abs(db.left[left])) < np.argmax(np.abs(db.right[left]))      # left ear first
    assert np.sum(db.left[left] ** 2) > np.sum(db.right[left] ** 2)                    # and louder


def test_binaural_render_with_measured_hrtf(tmp_path):
    from simulator.if_modules.orchestration import simulate_scene
    from simulator.uf.w151_config import SceneConfigValidator
    sofa = _fake_sofa(tmp_path / "s.sofa")
    cfg = {"scene_id": "hb", "seed": 3, "room": {"type": "shoebox", "dimensions": {"L": 8.0, "W": 6.0, "H": 3.0}},
           "materials": {"default": "anechoic"}, "sources": [{"source_id": "s0", "position": [2.0, 1.5, 3.0]}],
           "receivers": [{"receiver_id": "head", "position": [4.0, 1.5, 3.0], "binaural": True,
                          "hrtf": {"sofa": sofa}, "noise_floor_dbfs": -70.0}],
           "motion": {"duration_s": 1.0}, "ism_order": 1, "output_dir": str(tmp_path / "out")}
    b = load_scene(simulate_scene(SceneConfigValidator().validate(cfg))["manifest_path"])
    assert b.receiver_ids == ["head.L", "head.R"]
    hrtf = [r for r in b.manifest["receivers"] if r["receiver_id"] == "head.R"][0].get("hrtf")
    assert hrtf and hrtf["sofa"] == sofa
    f, Pl = signal.welch(b.references[0, 0], FS, nperseg=1024)
    _, Pr = signal.welch(b.references[0, 1], FS, nperseg=1024)
    assert 10 * np.log10(Pr.sum() / Pl.sum()) > 6.0                   # source on the right (-x)


def test_hrtf_requires_existing_sofa_and_binaural():
    from simulator.config_resolver import check_profile, resolve_config
    base = {"scene_id": "x", "room": {"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
            "sources": [{"source_id": "s0", "position": [1.0, 1.5, 1.0]}], "motion": {"duration_s": 1.0}}
    for rec in ({"receiver_id": "h", "position": [2.0, 1.5, 2.0], "binaural": True, "hrtf": {"sofa": "missing.sofa"}},
                {"receiver_id": "h", "position": [2.0, 1.5, 2.0], "hrtf": {"sofa": __file__}}):
        errs, _, _ = check_profile(resolve_config({**base, "receivers": [rec]}))
        assert any("hrtf" in e for e in errs), errs


def test_planner_randomises_hrtf_subjects(tmp_path):
    from datagen.assets import build_synthetic_library
    from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools
    lib = build_synthetic_library(str(tmp_path / "a"), n_speakers=6, utt_s=2.0, seed=1)
    subjects = [str(tmp_path / f"pp{k}.sofa") for k in range(3)]
    prior = ScenarioPrior(arrays=("binaural",), duration_s=3.0, n_speakers=(1, 2), hrtf_sofa=subjects)
    rooms = make_room_catalog(prior)
    pools = split_pools(lib, rooms, {"train": 1.0})
    plans = sample_scenarios(prior, 30, lib, pools, rooms, "train", seed=2)
    used = {p["config"]["receivers"][0]["hrtf"]["sofa"] for p in plans}
    assert used == set(subjects)
    assert all(p["config"]["receivers"][0]["binaural"] for p in plans)


# --- AMI ----------------------------------------------------------------------------

def _fake_ami(tmp_path):
    meeting = "XX0001a"
    meetings_xml = (f'<?xml version="1.0"?><nite:root xmlns:nite="x"><meeting observation="{meeting}">'
                    '<speaker channel="0" nxt_agent="A" global_name="P001" role="PM"/>'
                    '<speaker channel="1" nxt_agent="B" global_name="P002" role="ID"/></meeting></nite:root>')

    def words(spans, prefix):
        ws = []
        for k, (t0, t1) in enumerate(spans):
            for j, t in enumerate(np.arange(t0, t1, 0.5)):
                ws.append(f'<w nite:id="{prefix}{k}_{j}" starttime="{t:.2f}" endtime="{t + 0.4:.2f}">w{k}{j}</w>')
            ws.append(f'<w nite:id="{prefix}p{k}" starttime="{t1:.2f}" endtime="{t1:.2f}" punc="true">.</w>')
        return '<?xml version="1.0"?><nite:root xmlns:nite="x">' + "".join(ws) + "</nite:root>"

    z = tmp_path / "ann.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("corpusResources/meetings.xml", meetings_xml)
        zf.writestr(f"words/{meeting}.A.words.xml", words([(1.0, 4.5), (20.0, 23.5)], "a"))
        zf.writestr(f"words/{meeting}.B.words.xml", words([(10.0, 13.5), (30.0, 33.5)], "b"))
    d = tmp_path / meeting
    d.mkdir()
    rng = np.random.default_rng(0)
    T = 40 * FS
    for c in range(1, 9):
        wavfile.write(str(d / f"{meeting}.Array1-{c:02d}.wav"), FS, (rng.standard_normal(T) * 1000).astype(np.int16))
    return str(z), str(d), meeting


def test_ami_parse_windows_and_registry(tmp_path):
    from datatools.ami import parse_meeting, registry_row, single_speaker_windows
    from datatools.real_sessions import validate_rows
    z, _, m = _fake_ami(tmp_path)
    spk = parse_meeting(z, m)
    assert {s.global_id for s in spk.values()} == {"P001", "P002"}
    assert all("." not in w for s in spk.values() for _, _, w in s.words)          # punctuation dropped
    wins = single_speaker_windows(spk, min_s=2.5, max_s=6.0)
    assert len(wins) == 4 and {w["speaker"] for w in wins} == {"P001", "P002"}
    row = registry_row(m, spk)
    flat = {k: (";".join(v) if isinstance(v, list) else str(v).lower() if isinstance(v, bool) else v)
            for k, v in row.items()}
    assert validate_rows([flat])[0]["has_transcript"] is True


def test_ami_superposition_scene_contract(tmp_path):
    from datatools.ami import build_meeting_scenes
    z, d, m = _fake_ami(tmp_path)
    recs = build_meeting_scenes(z, d, m, str(tmp_path / "scenes"), 3, np.random.default_rng(1))
    assert len(recs) == 3
    for r in recs:
        b = load_scene(r["manifest"])                                   # checksums + contract
        assert b.mixture.shape[0] == 8 and b.references.shape[:2] == (2, 8)
        np.testing.assert_allclose(b.mixture, b.references.sum(axis=0), atol=1e-6)
        assert len(r["speakers"]) == 2 and r["speakers"][0] != r["speakers"][1]
        assert all(b.manifest["labels"]["vad"][s] for s in b.source_ids)
        assert b.manifest["geometry"]["pairs"] == []


# --- evaluation glue ------------------------------------------------------------------

def test_identical_streams_are_transcribed_once():
    from evaluation.asr import StaticAsrBackend, stream_wer
    be = StaticAsrBackend([[(0.0, 1.0, "hello world")], [(0.0, 1.0, "hello world")]])
    x = np.random.default_rng(0).standard_normal(1000)
    r = stream_wer(be, np.stack([x, x]), FS, "hello world")
    assert be.calls == 1 and r["wer"] == 0.0


def test_neural_agc_front_end_is_scale_invariant(tmp_path):
    pytest.importorskip("torch")
    from datatools.loader import SceneBundle
    from training.neural import MaskNet, NetConfig, NeuralSeparator
    net = MaskNet(NetConfig(hidden=16, layers=1)).eval()
    rng = np.random.default_rng(0)
    mix = rng.standard_normal((2, FS)).astype(np.float32) * 0.01
    man = {"receivers": [{"effective_position": [0, 0, 0]}, {"effective_position": [0.05, 0, 0]}],
           "render": {"reference_receiver": "m0"}}
    sep = NeuralSeparator(net, input_rms_dbfs=-25.0)

    def run(scale):
        b = SceneBundle("s", FS, ["a", "b"], ["m0", "m1"], mix * scale, np.zeros((2, 2, FS), np.float32), None, man)
        return sep.separate(b)[0]
    np.testing.assert_allclose(run(1.0) * 100.0, run(100.0), rtol=1e-3, atol=1e-6)


def test_neural_feature_coral_identity_and_shift(tmp_path):
    """CORAL on the separator's per-bin input: same-domain fit is ~identity; a level
    shift in the target is undone, so the adapted separator sees source statistics."""
    pytest.importorskip("torch")
    from datatools.loader import SceneBundle
    from training.neural import MaskNet, NetConfig, NeuralSeparator, fit_feature_coral, from_bins, to_bins
    net = MaskNet(NetConfig(hidden=16, layers=1)).eval()
    man = {"receivers": [{"effective_position": [0, 0, 0]}, {"effective_position": [0.05, 0, 0]}],
           "render": {"reference_receiver": "m0"}}
    rng = np.random.default_rng(0)

    def bundle(scale):
        mix = (rng.standard_normal((2, FS)) * scale).astype(np.float32)
        return SceneBundle("s", FS, ["a", "b"], ["m0", "m1"], mix, np.zeros((2, 2, FS), np.float32), None, man)
    sep = NeuralSeparator(net)
    src = [bundle(0.01) for _ in range(6)]
    fb = sep.bin_features(src[0])
    np.testing.assert_allclose(to_bins(from_bins(fb), net.cfg), fb)            # layout round trip
    ad = fit_feature_coral(sep, src, src)
    np.testing.assert_allclose(ad.transform(fb), fb, atol=1e-2)
    tgt = [bundle(0.1) for _ in range(6)]                                       # +20 dB: log-mag shifts by ln(100)
    ad2 = fit_feature_coral(sep, src, tgt)
    lm_src = np.mean([sep.bin_features(b)[..., 0].mean() for b in src])
    lm_ad = np.mean([ad2.transform(sep.bin_features(b))[..., 0].mean() for b in tgt])
    assert abs(lm_ad - lm_src) < 0.05
    out, info = NeuralSeparator(net, adapter=ad2).separate(tgt[0])
    assert info["adapted"] and np.all(np.isfinite(out))
