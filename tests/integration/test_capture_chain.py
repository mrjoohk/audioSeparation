"""Integration tests for IF-W141..W144: Capture Device Chain."""
import pytest
import numpy as np

from simulator.if_modules.capture import CaptureDeviceChain, apply_device_chain
from simulator.types import SceneConfig, MicSpec, ArrayConfig


def make_config(seed=7) -> SceneConfig:
    return SceneConfig(
        scene_id="it_cap_001",
        seed=seed,
        schema_version="1.0.0",
        room={"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
        materials={},
        sources=[{"source_id": "s0", "position": [1.0, 1.0, 1.0]}],
        receivers=[
            {"receiver_id": f"r{i}", "position": [2.0 + i * 0.05, 1.0, 2.0],
             "noise_floor_dbfs": -60.0, "gain_db": 0.0}
            for i in range(4)
        ],
        sample_rate=16000,
        ism_order=3,
    )


def make_mic_specs(C: int) -> list:
    return [
        MicSpec(
            mic_id=f"m{c}",
            freq_response_db=np.zeros(2),
            freq_bins_hz=np.array([100.0, 8000.0]),
            pattern_type="omni",
            sensitivity_db=0.0,
        )
        for c in range(C)
    ]


def test_full_device_chain_output_shape():
    """4-channel signal through full chain → output shape unchanged."""
    config = make_config()
    C, N = 4, 16000
    rng = np.random.default_rng(0)
    signals = rng.standard_normal((C, N)).astype(np.float32) * 0.1

    chain = CaptureDeviceChain(config, seed=42)
    mic_specs = make_mic_specs(C)
    out, meta = chain.process_full_chain(signals, mic_specs)

    assert out.shape == (C, N), f"Output shape {out.shape} ≠ ({C}, {N})"
    assert out.dtype == np.float32


def test_full_chain_snr_in_metadata():
    """Metadata should contain snr_per_channel_db with C values."""
    config = make_config()
    C, N = 4, 16000
    rng = np.random.default_rng(1)
    signals = rng.standard_normal((C, N)).astype(np.float32) * 0.3

    chain = CaptureDeviceChain(config, seed=0)
    mic_specs = make_mic_specs(C)
    _, meta = chain.process_full_chain(signals, mic_specs)

    assert "snr_per_channel_db" in meta
    assert len(meta["snr_per_channel_db"]) == C


def test_noise_degrades_snr():
    """Signal after noise addition should have lower SNR than ideal."""
    config = make_config()
    C, N = 2, 16000
    amplitude = 0.1  # ~-20 dBFS
    signals = (np.ones((C, N)) * amplitude).astype(np.float32)

    chain = CaptureDeviceChain(config, seed=3)
    mic_specs = make_mic_specs(C)
    out, meta = chain.process_full_chain(signals, mic_specs)

    # Output should differ from input (noise was added)
    assert not np.allclose(out, signals, atol=1e-4), "Chain had no effect on signal"


def test_apply_device_chain_convenience():
    """Module-level apply_device_chain should work identically."""
    config = make_config()
    C, N = 2, 8000
    rng = np.random.default_rng(2)
    signals = rng.standard_normal((C, N)).astype(np.float32) * 0.1
    mic_specs = make_mic_specs(C)

    out, meta = apply_device_chain(signals, config, mic_specs)
    assert out.shape == (C, N)
    assert isinstance(meta, dict)


def test_chain_with_bandwidth_impairment():
    """Bandwidth impairment should attenuate high-frequency content."""
    from simulator.types import ImpairmentSpec
    config = make_config()
    config = SceneConfig(
        scene_id="it_cap_bw",
        seed=0,
        schema_version="1.0.0",
        room=config.room,
        materials={},
        sources=config.sources,
        receivers=config.receivers,
        sample_rate=16000,
        ism_order=3,
        impairments={"type": "bandwidth", "bandwidth_hz": 4000.0},
    )

    C, N = 1, 16000
    # Generate signal with high-frequency content
    fs = 16000
    t = np.arange(N) / fs
    sig = (np.sin(2 * np.pi * 6000 * t)).astype(np.float32)
    signals = sig.reshape(1, -1)

    chain = CaptureDeviceChain(config, seed=0)
    mic_specs = make_mic_specs(C)
    out, meta = chain.process_full_chain(signals, mic_specs)

    # Energy at 6 kHz should be reduced (above 4 kHz cutoff)
    fft_in = np.abs(np.fft.rfft(signals[0]))
    fft_out = np.abs(np.fft.rfft(out[0]))
    freqs = np.fft.rfftfreq(N, 1.0 / fs)
    mask_6k = (freqs >= 5500) & (freqs <= 6500)

    energy_in = np.sum(fft_in[mask_6k] ** 2)
    energy_out = np.sum(fft_out[mask_6k] ** 2)
    attenuation_db = 10 * np.log10((energy_in + 1e-30) / (energy_out + 1e-30))
    assert attenuation_db > 20.0, \
        f"6 kHz attenuation only {attenuation_db:.1f} dB (expected > 20 dB)"


def test_per_channel_gain_applied():
    """Audit F-09: receivers[1].gain_db must affect channel 1 (only receivers[0] was read)."""
    cfg = SceneConfig(
        scene_id="gain", seed=3, schema_version="1.0.0",
        room={"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
        materials={}, sources=[{"source_id": "s0", "position": [1, 1, 1]}],
        receivers=[
            {"receiver_id": "r0", "position": [2, 1, 2]},
            {"receiver_id": "r1", "position": [3, 1, 2], "gain_db": 12.0},
        ],
        sample_rate=16000,
    )
    rng = np.random.default_rng(0)
    x = (0.05 * rng.standard_normal(16000)).astype(np.float32)
    sig = np.stack([x, x])
    out, meta = apply_device_chain(sig, cfg, make_mic_specs(2))
    ratio_db = 20 * np.log10(np.std(out[1]) / np.std(out[0]))
    assert ratio_db == pytest.approx(12.0, abs=0.2)
    assert len(meta["clipped_samples"]) == 2


def test_noise_component_exposed():
    cfg = make_config()
    chain = CaptureDeviceChain(cfg, seed=cfg.seed)
    C = len(cfg.receivers)
    sig = np.zeros((C, 8000), dtype=np.float32)
    out, _ = chain.process_full_chain(sig, make_mic_specs(C))
    # Silent input: the observed signal is exactly the exposed noise (no clipping/codec).
    np.testing.assert_allclose(out, chain.last_noise_component, atol=1e-7)
