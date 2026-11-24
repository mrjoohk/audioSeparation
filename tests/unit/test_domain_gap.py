"""Stage 7: curriculum sampling (REQ-301), calibration (REQ-302), augmentation (REQ-303),
adaptation diagnostics (REQ-304)."""
import time

import numpy as np
import pytest

from training.adaptation import CoralAdapter, domain_bce
from training.augment import AugmentConfig, apply_linear, augment_scene, sample_params
from training.calibration import alpha_for_rt60, blind_rt60, fit_profile, kl_divergence
from training.curriculum import Curriculum, MixedDomainSampler, Prefetcher

FS = 16000


# --- REQ-301 ---------------------------------------------------------------------

def test_mixed_domain_ratio_over_10k_steps():
    s = MixedDomainSampler(pools={"synthetic": [f"s{i}" for i in range(50)], "real": [f"r{i}" for i in range(7)]},
                           weights={"synthetic": 0.5, "real": 0.5}, batch_size=6, seed=1)
    worst = 0.0
    for step in range(10_000):
        batch = s.next_batch()
        assert len(batch) == 6
        if step >= 10:
            worst = max(worst, abs(s.ratios()["real"] - 0.5))
    assert worst < 0.05
    assert abs(s.ratios()["synthetic"] - 0.5) < 0.001


def test_curriculum_moves_from_easy_to_hard():
    cur = Curriculum(start={"easy": 1.0}, end={"easy": 0.2, "hard": 0.8}, ramp_steps=100)
    assert cur.weights(0)["hard"] == 0.0 and cur.weights(100)["hard"] == pytest.approx(0.8)
    s = MixedDomainSampler(pools={"synthetic": []}, weights={"synthetic": 1.0}, batch_size=10, seed=0,
                           tiers={"synthetic": {"easy": ["e1", "e2"], "hard": ["h1", "h2"]}}, curriculum=cur)
    first = [i for _, i in s.next_batch()]
    for _ in range(200):
        last = [i for _, i in s.next_batch()]
    assert all(i.startswith("e") for i in first)
    assert sum(i.startswith("h") for i in last) >= 5


def test_prefetcher_keeps_wait_below_5pct():
    s = MixedDomainSampler(pools={"a": ["x"], "b": ["y"]}, weights={"a": 1, "b": 1}, batch_size=4, seed=0)

    def load(item):
        time.sleep(0.0005)          # I/O per item
        return item

    pf = Prefetcher(s, load, depth=16, workers=2)
    time.sleep(0.05)                # warm-up fill
    for _ in range(150):
        pf.get()
        time.sleep(0.004)           # training step
    pf.close()
    assert pf.wait_fraction < 0.05


# --- REQ-302 ---------------------------------------------------------------------

def _reverberant_bursts(rt60, seed=0, n_bursts=12):
    rng = np.random.default_rng(seed)
    x = np.zeros(FS * 12)
    t = np.arange(int(rt60 * 1.5 * FS)) / FS
    tail = rng.standard_normal(len(t)) * np.exp(-6.9 * t / rt60)
    for k in range(n_bursts):
        p = k * FS
        x[p:p + 3000] += rng.standard_normal(3000)
        x[p + 3000:p + 3000 + len(tail)] += tail[: max(0, min(len(tail), len(x) - p - 3000))]
    return x + 1e-5 * rng.standard_normal(len(x))


@pytest.mark.parametrize("rt60", [0.3, 0.5, 0.8])
def test_blind_rt60_on_known_decays(rt60):
    est = blind_rt60(_reverberant_bursts(rt60), FS)
    assert abs(est - rt60) / rt60 < 0.15


def test_profile_and_inverse_sabine():
    prof = fit_profile({"a": 0.48, "b": 0.52, "c": None, "d": 0.5}, data_version="real-v1")
    assert prof["fit_sessions"] == ["a", "b", "d"] and prof["rt60_median_s"] == pytest.approx(0.5)
    dims = {"L": 6.0, "W": 5.0, "H": 3.0}
    a = alpha_for_rt60(dims, 0.5)
    V, S = 90.0, 2 * (30 + 18 + 15)
    assert 0.161 * V / (S * a) == pytest.approx(0.5)


def test_kl_divergence():
    rng = np.random.default_rng(0)
    p = rng.normal(0.5, 0.05, 500)
    assert kl_divergence(p, rng.normal(0.5, 0.05, 500)) < 0.1
    assert kl_divergence(p, rng.normal(0.8, 0.05, 500)) > 1.0


# --- REQ-303 ---------------------------------------------------------------------

def test_augmentation_is_linear_and_keeps_phase_differences():
    rng = np.random.default_rng(3)
    refs = rng.standard_normal((2, 3, 8000))
    mix = refs.sum(axis=0)
    p = sample_params(rng, 3, AugmentConfig(noise_prob=0.0, bandlimit_prob=0.0))
    m_aug, r_aug = augment_scene(mix, refs, FS, p)
    np.testing.assert_allclose(m_aug, r_aug.sum(axis=0), atol=1e-9)
    X = np.fft.rfft(mix, axis=-1)
    Y = np.fft.rfft(m_aug, axis=-1)
    ipd_x = np.angle(X[1] * np.conj(X[0]))
    ipd_y = np.angle(Y[1] * np.conj(Y[0]))
    # identical filters on every channel: IPD unchanged except for a few bins
    # disturbed by the IIR start-up transient of a finite signal
    dev = np.abs(np.angle(np.exp(1j * (ipd_x - ipd_y))))
    assert np.percentile(dev, 95) < 0.01 and np.median(dev) < 2e-3


# --- REQ-304 ---------------------------------------------------------------------

def test_coral_aligns_statistics_and_bce_diagnostic():
    rng = np.random.default_rng(1)
    F, N, D = 4, 3000, 5
    src = rng.standard_normal((F, N, D))
    A = rng.standard_normal((D, D)) * 0.5 + np.eye(D)
    tgt = np.einsum("fnd,de->fne", rng.standard_normal((F, N, D)), A) + 2.0
    ones = np.ones((F, N, 1))
    ad = CoralAdapter()
    ad.accumulate(np.concatenate([src, ones], -1), "source")
    ad.accumulate(np.concatenate([tgt, ones], -1), "target")
    ad.fit()
    out = ad.transform(np.concatenate([tgt, ones], -1))[..., :-1]
    assert np.allclose(out.mean(axis=1), src.mean(axis=1), atol=0.05)
    before = domain_bce(src[0], tgt[0])
    after = domain_bce(src[0], out[0])
    assert before < 0.3 and after > 0.6


def test_closed_loop_calibration_corrects_biased_simulator():
    """A renderer+estimator chain that reads 25 % low and compresses the spread is
    corrected to KL <= 0.1 within three iterations."""
    from training.calibration import closed_loop_calibrate
    rng = np.random.default_rng(0)
    measured = rng.normal(0.55, 0.12, 120).clip(0.2, None)

    def regenerate(targets):
        t = np.asarray(targets)
        return list(0.75 * (0.6 * t + 0.4 * t.mean()) + rng.normal(0, 0.01, len(t)))

    one_shot = kl_divergence(measured, regenerate(list(measured)), bins=np.linspace(0, 2, 11))
    res = closed_loop_calibrate(measured, regenerate, iterations=4)
    assert one_shot > 0.1
    assert res["converged"] and res["kl"] <= 0.1
