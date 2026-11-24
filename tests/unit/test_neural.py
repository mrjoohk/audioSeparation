"""Neural separator plumbing (REQ-401 / REQ-303 candidate)."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from training.neural import MaskNet, NetConfig, features, pit_loss, si_sdr_t


def test_masknet_shapes_and_range():
    cfg = NetConfig(hidden=32, layers=1)
    net = MaskNet(cfg)
    x = torch.randn(2, 16000)
    f, Xr = features(x, torch.roll(x, 3, dims=1), cfg)
    m = net(f)
    assert f.shape[-1] == 3 * (cfg.nfft // 2 + 1)
    assert m.shape == (2, 2, cfg.nfft // 2 + 1, Xr.shape[-1])
    assert float(m.min()) >= 0.0 and float(m.max()) <= 1.0


def test_pit_loss_is_permutation_invariant():
    torch.manual_seed(0)
    ref = torch.randn(3, 2, 8000)
    est = ref + 0.1 * torch.randn_like(ref)
    assert torch.allclose(pit_loss(est, ref), pit_loss(est.flip(1), ref))
    assert float(si_sdr_t(ref, ref).mean()) > 60


def test_tiny_training_run(tmp_path):
    from training.neural import train_net, load_net
    import os, json
    from datagen.assets import build_synthetic_library
    from datagen.planner import ScenarioPrior, make_room_catalog, sample_scenarios, split_pools
    from datagen.publish import generate_dataset
    lib = build_synthetic_library(str(tmp_path / "a"), n_speakers=6, utts_per_speaker=1, utt_s=1.5, seed=1)
    pr = ScenarioPrior(arrays=("pair10",), duration_s=1.5, ism_order=1, n_speakers=(2, 2), tiers={"medium": 0.2},
                       tier_weights={"medium": 1}, noise_prob=0.0, event_prob=0.0, storage_profile="training",
                       n_room_templates=4)
    rooms = make_room_catalog(pr)
    pools = split_pools(lib, rooms, {"train": 1.0})
    plans = sample_scenarios(pr, 3, lib, pools, rooms, "train", seed=2, output_dir=str(tmp_path / "o"))
    generate_dataset(plans, str(tmp_path / "o"))
    sc = [(str(tmp_path / "o" / p["config"]["scene_id"] / "scene_manifest.json"), None) for p in plans]
    e1 = train_net(sc, str(tmp_path / "m1"), steps=3, batch=2, seg_s=1.0, cfg=NetConfig(hidden=16, layers=1))
    e2 = train_net(sc, str(tmp_path / "m2"), steps=3, batch=2, seg_s=1.0, cfg=NetConfig(hidden=16, layers=1))
    assert e1["checkpoint"]["sha256"] == e2["checkpoint"]["sha256"]          # seeded → reproducible
    from datatools.loader import load_scene
    from training.neural import NeuralSeparator
    b = load_scene(sc[0][0])
    est, info = NeuralSeparator(load_net(str(tmp_path / "m1" / "masknet.pt"))).separate(b)
    assert est.shape == (2, b.mixture.shape[1]) and np.all(np.isfinite(est))


def test_threaded_loader_is_reproducible_and_shaped():
    from training.neural import _ThreadedBatches
    rng = np.random.default_rng(0)
    data = [(rng.standard_normal((3, 4000)).astype(np.float32), rng.standard_normal((2, 4000)).astype(np.float32), 0,
             rng.standard_normal((2, 3, 4000)).astype(np.float32)) for _ in range(5)]

    def run():
        ld = _ThreadedBatches(data, 3000, None, 4, seed=7, threads=3)
        out = [ld.get() for _ in range(3)]
        ld.close()
        return out
    a, b = run(), run()
    for x, y in zip(a, b):
        for u, v in zip(x, y):
            assert torch.equal(u, v)
    ref, par, tgt = a[0]
    assert ref.shape == (4, 3000) and par.shape == (4, 3000) and tgt.shape == (4, 2, 3000)
    assert not torch.equal(a[0][0], a[1][0])                     # steps differ
