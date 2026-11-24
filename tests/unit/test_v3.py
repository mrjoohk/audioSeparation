"""v3 real-data training (design §16): domain-weighted sampling, channel subset and level, data separation."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from training.neural import domain_sampler, load_training_set  # noqa: E402


@pytest.fixture(scope="module")
def rr():
    spec = importlib.util.spec_from_file_location("run_real_v3", ROOT / "scripts" / "run_real_data_experiments.py")
    mod = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["x"]
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def test_domain_sampler_follows_weights_not_sizes():
    draw = domain_sampler([10, 1000], [0.5, 0.5])
    idx = draw(np.random.default_rng(0), 20000)
    small = np.mean(idx < 10)
    assert abs(small - 0.5) < 0.02                      # 50 % from the small domain despite 1 % of the items
    assert idx.min() >= 0 and idx.max() < 1010
    with pytest.raises(ValueError):
        domain_sampler([0, 5], [0.5, 0.5])              # weighted domain without items


def test_load_training_set_channel_subset_and_level(tmp_path):
    from datatools.ami import write_superposition_scene
    rng = np.random.default_rng(1)
    clips = [0.01 * rng.standard_normal((8, 16000)).astype(np.float32) for _ in range(2)]
    mp = write_superposition_scene(str(tmp_path), "s_000", clips, [0.0, 0.5], [[(0.0, 1.0)], [(0.0, 1.0)]], {})
    (mix, refs, ref, all_refs), = load_training_set([(mp, None)], channels=[0, 1, 7], level_dbfs=-20.0)
    assert mix.shape[0] == 3 and all_refs.shape[:2] == (2, 3) and ref == 0
    assert 20 * np.log10(np.sqrt(np.mean(mix[0].astype(np.float64) ** 2))) == pytest.approx(-20.0, abs=1e-3)
    np.testing.assert_allclose(all_refs.sum(0), mix, atol=1e-6)          # one gain for mixture and references
    np.testing.assert_allclose(refs, all_refs[:, 0])
    with pytest.raises(ValueError):
        load_training_set([(mp, None)], channels=[1, 2])               # reference mic missing


def test_v3_training_meetings_are_disjoint_from_dev_and_every_blind_set(rr):
    assert not set(rr.AMI_TRAIN) & set(rr.BLIND3_MEETINGS + rr.BLIND2_MEETINGS + rr.AMI_MEETINGS)
    assert not any(m.startswith("TS") for m in rr.AMI_TRAIN)           # no TNO room in training
    assert len(rr.BLIND3_MEETINGS) == 16 and not set(rr.BLIND3_MEETINGS) & set(rr.BLIND2_MEETINGS)
    if not rr.AMI_ZIP.exists():
        pytest.skip("AMI annotations not available")
    rr.check_train_disjoint(list(rr.AMI_TRAIN), list(rr.BLIND3_MEETINGS) + ["ES2002a", "IS1009a"])
    with pytest.raises(ValueError):
        rr.check_train_disjoint(["ES2004a"], ["ES2004b"])              # same team -> shared speakers


def test_train_net_with_domains_records_domain_mix(tmp_path):
    from datatools.ami import write_superposition_scene
    from training.neural import NetConfig, train_net
    rng = np.random.default_rng(2)
    scenes = []
    for k in range(2):
        clips = [0.01 * rng.standard_normal((8, 24000)).astype(np.float32) for _ in range(2)]
        scenes.append((write_superposition_scene(str(tmp_path / "sc"), f"s_{k:03d}", clips, [0.0, 0.5],
                                                 [[(0.0, 1.0)], [(0.0, 1.0)]], {}), None))
    exp = train_net(None, str(tmp_path / "m"), steps=2, batch=2, seg_s=1.0, cfg=NetConfig(hidden=16, layers=1),
                    domains=[{"name": "real", "scenes": scenes[:1], "weight": 0.5, "channels": [0, 1, 7],
                              "level_dbfs": -25.0},
                             {"name": "other", "scenes": scenes[1:], "weight": 0.5}])
    names = [d["name"] for d in exp["data"]["domains"]]
    assert names == ["real", "other"] and exp["data"]["n_scenes"] == 2
