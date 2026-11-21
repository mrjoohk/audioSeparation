"""
Unit tests for UF-W124: RIR Rendering
(w124_rir_rendering.py)

Tests:
    test_rir_direct_peak          – UF-W124-01
    test_rir_drr_anechoic         – UF-W124-01
    test_rir_reproducibility      – UF-W124-01
    test_interpolate_endpoints    – UF-W124-03
    test_render_waveform_length   – UF-W124-04
    test_render_empty_raises      – UF-W124-04
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from simulator.types import (
    DirectPath,
    ImageSource,
    LateReverbSpec,
    OcclusionResult,
    ReflectionData,
    RIR,
    BRIR,
)
from simulator.uf.w124_rir_rendering import (
    generate_static_rir,
    generate_brir,
    interpolate_rir_segment,
    render_waveform,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_direct_path(
    distance_m: float = 1.0,
    fs: int = 16000,
    c: float = 343.0,
    attenuation: float = 1.0,
) -> DirectPath:
    delay_s = distance_m / c
    return DirectPath(
        source_id="src0",
        receiver_id="mic0",
        distance_m=distance_m,
        delay_s=delay_s,
        delay_samples=int(round(delay_s * fs)),
        attenuation_linear=attenuation,
        doa_az_rad=0.0,
        doa_el_rad=0.0,
        air_atten_db=0.0,
        doppler_factor=1.0,
    )


def _make_reflection_data(
    rt60_s: float = 0.3,
    mixing_time_ms: float = 20.0,
    seed: int = 42,
    image_sources=None,
) -> ReflectionData:
    if image_sources is None:
        image_sources = []
    return ReflectionData(
        image_sources=image_sources,
        late_tail_spec=LateReverbSpec(rt60_s=rt60_s, mixing_time_ms=mixing_time_ms, seed=seed),
    )


def _make_no_occlusion() -> OcclusionResult:
    return OcclusionResult(
        source_id="src0",
        receiver_id="mic0",
        visible=True,
        blocking_object_id=None,
        loss_db=0.0,
        loss_db_per_band=np.zeros(6, dtype=np.float64),
    )


def _make_full_occlusion(loss_db: float = 60.0) -> OcclusionResult:
    return OcclusionResult(
        source_id="src0",
        receiver_id="mic0",
        visible=False,
        blocking_object_id="wall_01",
        loss_db=loss_db,
        loss_db_per_band=np.full(6, loss_db, dtype=np.float64),
    )


def _make_rir_from_components(
    distance_m: float = 1.0,
    fs: int = 16000,
    rt60_s: float = 0.3,
    mixing_time_ms: float = 20.0,
    occlusion_loss_db: float = 0.0,
    seed: int = 42,
) -> RIR:
    dp = _make_direct_path(distance_m=distance_m, fs=fs)
    refl = _make_reflection_data(rt60_s=rt60_s, mixing_time_ms=mixing_time_ms, seed=seed)
    if occlusion_loss_db == 0.0:
        occ = _make_no_occlusion()
    else:
        occ = _make_full_occlusion(occlusion_loss_db)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return generate_static_rir(dp, refl, occ, fs=fs)


# ---------------------------------------------------------------------------
# UF-W124-01: generate_static_rir
# ---------------------------------------------------------------------------

class TestGenerateStaticRIR:
    def test_returns_rir_dataclass(self):
        rir = _make_rir_from_components()
        assert isinstance(rir, RIR)

    def test_h_is_float32(self):
        rir = _make_rir_from_components()
        assert rir.h.dtype == np.float32

    def test_rir_direct_peak(self):
        """Anechoic scene: largest peak should be at or very near the direct-path delay."""
        fs = 16000
        distance_m = 1.0
        c = 343.0
        expected_delay = int(round(distance_m / c * fs))  # ≈ 47

        dp = _make_direct_path(distance_m=distance_m, fs=fs, c=c, attenuation=1.0)
        # Tiny tail to make it near-anechoic
        refl = _make_reflection_data(rt60_s=0.05, mixing_time_ms=200.0, seed=42)
        occ = _make_no_occlusion()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            rir = generate_static_rir(dp, refl, occ, fs=fs)

        peak_idx = int(np.argmax(np.abs(rir.h)))
        assert abs(peak_idx - expected_delay) <= 1, (
            f"Peak at sample {peak_idx}, expected {expected_delay} ± 1"
        )

    def test_rir_drr_anechoic(self):
        """Near-anechoic scene (high absorption, late mixing time) → DRR > 30 dB."""
        dp = _make_direct_path(distance_m=1.0, fs=16000, attenuation=1.0)
        # Use extremely short RT60 and very late mixing time → essentially anechoic
        refl = _make_reflection_data(rt60_s=0.02, mixing_time_ms=500.0, seed=42)
        occ = _make_no_occlusion()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            rir = generate_static_rir(dp, refl, occ, fs=16000)

        assert rir.drr_db > 30.0, (
            f"Expected DRR > 30 dB for near-anechoic scene, got {rir.drr_db:.1f} dB"
        )

    def test_rir_reproducibility(self):
        """Same inputs twice → identical h arrays."""
        rir1 = _make_rir_from_components(seed=42)
        rir2 = _make_rir_from_components(seed=42)
        np.testing.assert_array_equal(rir1.h, rir2.h)

    def test_rir_different_seeds_differ(self):
        """Different seeds → different late tail → different h."""
        rir1 = _make_rir_from_components(seed=42)
        rir2 = _make_rir_from_components(seed=99)
        assert not np.allclose(rir1.h, rir2.h)

    def test_rir_length_bounded_by_max(self):
        """RIR length must not exceed MAX_RIR_DURATION_S * fs."""
        from simulator.types import MAX_RIR_DURATION_S
        fs = 16000
        rir = _make_rir_from_components(rt60_s=3.0, fs=fs)
        assert len(rir.h) <= int(MAX_RIR_DURATION_S * fs) + 1

    def test_rir_length_at_least_min(self):
        """RIR length must be at least 0.5 s of samples for very short RT60."""
        fs = 16000
        rir = _make_rir_from_components(rt60_s=0.05, fs=fs)
        assert len(rir.h) >= int(0.5 * fs)

    def test_occlusion_attenuates_direct_path(self):
        """Heavy occlusion should reduce the amplitude at the direct-path sample."""
        fs = 16000
        dp = _make_direct_path(distance_m=1.0, fs=fs, attenuation=1.0)
        refl = _make_reflection_data(rt60_s=0.05, mixing_time_ms=500.0, seed=42)

        occ_none  = _make_no_occlusion()
        occ_heavy = _make_full_occlusion(loss_db=40.0)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            rir_clear = generate_static_rir(dp, refl, occ_none,  fs=fs)
            rir_occ   = generate_static_rir(dp, refl, occ_heavy, fs=fs)

        delay = dp.delay_samples
        assert abs(float(rir_clear.h[delay])) > abs(float(rir_occ.h[delay]))

    def test_rt60_stored_positive(self):
        rir = _make_rir_from_components(rt60_s=0.5)
        assert rir.rt60_measured_s >= 0.0

    def test_peak_delay_samples_field(self):
        """peak_delay_samples should correspond to argmax(|h|)."""
        rir = _make_rir_from_components()
        peak = int(np.argmax(np.abs(rir.h)))
        assert rir.peak_delay_samples == peak


# ---------------------------------------------------------------------------
# UF-W124-02: generate_brir
# ---------------------------------------------------------------------------

class TestGenerateBRIR:
    def _make_rir(self, fs=16000) -> RIR:
        return _make_rir_from_components(fs=fs)

    def test_returns_brir(self):
        rir = self._make_rir()
        brir = generate_brir(rir, None, None, None, doa_az_rad=0.0, doa_el_rad=0.0)
        assert isinstance(brir, BRIR)

    def test_brir_shape_2_by_N(self):
        """BRIR must be 2 × N (left, right)."""
        rir = self._make_rir()
        brir = generate_brir(rir, None, None, None, doa_az_rad=0.5, doa_el_rad=0.1)
        assert brir.h.ndim == 2
        assert brir.h.shape[0] == 2

    def test_brir_dtype_float32(self):
        rir = self._make_rir()
        brir = generate_brir(rir, None, None, None, doa_az_rad=0.0, doa_el_rad=0.0)
        assert brir.h.dtype == np.float32

    def test_brir_doa_stored_correctly(self):
        rir = self._make_rir()
        az_rad = 0.785  # 45°
        el_rad = 0.1
        brir = generate_brir(rir, None, None, None, doa_az_rad=az_rad, doa_el_rad=el_rad)
        assert brir.doa_az_deg == pytest.approx(math.degrees(az_rad), abs=0.1)
        assert brir.doa_el_deg == pytest.approx(math.degrees(el_rad), abs=0.1)

    def test_brir_left_right_differ_for_lateral_source(self):
        """Source at 90° azimuth → left and right channels should differ."""
        rir = self._make_rir()
        brir = generate_brir(rir, None, None, None,
                             doa_az_rad=math.pi / 2.0, doa_el_rad=0.0)
        left  = brir.h[0]
        right = brir.h[1]
        rms_diff = float(np.sqrt(np.mean((left - right) ** 2)))
        assert rms_diff > 1e-6, "Left and right channels should differ for lateral source"

    def test_brir_with_explicit_hrtf_grid(self):
        """Provide a simple synthetic HRTF grid and verify output shape."""
        rir = self._make_rir(fs=16000)
        n_taps = 64
        A, E = 5, 3
        az_grid = np.linspace(-math.pi, math.pi, A)
        el_grid = np.linspace(-math.pi / 4, math.pi / 4, E)
        # Simple identity-like filters
        hrtf = np.zeros((A, E, 2, n_taps), dtype=np.float64)
        hrtf[:, :, :, 0] = 1.0  # Dirac at sample 0 for both channels

        brir = generate_brir(rir, az_grid, el_grid, hrtf, doa_az_rad=0.0, doa_el_rad=0.0)
        assert brir.h.shape[0] == 2
        assert brir.h.shape[1] >= len(rir.h)


# ---------------------------------------------------------------------------
# UF-W124-03: interpolate_rir_segment
# ---------------------------------------------------------------------------

class TestInterpolateRIRSegment:
    def _rms_db(self, a: np.ndarray, b: np.ndarray) -> float:
        """RMS difference in dB relative to max amplitude."""
        diff = a.astype(np.float64) - b.astype(np.float64)
        rms_diff = np.sqrt(np.mean(diff ** 2))
        ref = max(np.max(np.abs(a)), np.max(np.abs(b)), 1e-30)
        return float(20.0 * np.log10(rms_diff / ref + 1e-120))

    def test_interpolate_endpoints(self):
        """alpha=0 → output matches rir_start; alpha=1 → output matches rir_end."""
        rng = np.random.default_rng(0)
        h1 = rng.standard_normal(100).astype(np.float32)
        h2 = rng.standard_normal(100).astype(np.float32)

        out0 = interpolate_rir_segment(h1, h2, alpha=0.0)
        out1 = interpolate_rir_segment(h1, h2, alpha=1.0)

        # Both are same length (100), no padding needed
        rms_db_0 = self._rms_db(out0, h1)
        rms_db_1 = self._rms_db(out1, h2)

        assert rms_db_0 < -80.0, (
            f"alpha=0 output differs from rir_start by {rms_db_0:.1f} dB (expected < -80 dB)"
        )
        assert rms_db_1 < -80.0, (
            f"alpha=1 output differs from rir_end by {rms_db_1:.1f} dB (expected < -80 dB)"
        )

    def test_interpolate_alpha_clamp_below(self):
        """alpha < 0 → clamped to 0 → same as alpha=0."""
        rng = np.random.default_rng(1)
        h1 = rng.standard_normal(50).astype(np.float32)
        h2 = rng.standard_normal(50).astype(np.float32)
        out_neg = interpolate_rir_segment(h1, h2, alpha=-0.5)
        out_0   = interpolate_rir_segment(h1, h2, alpha=0.0)
        np.testing.assert_array_almost_equal(out_neg, out_0, decimal=5)

    def test_interpolate_alpha_clamp_above(self):
        """alpha > 1 → clamped to 1 → same as alpha=1."""
        rng = np.random.default_rng(2)
        h1 = rng.standard_normal(50).astype(np.float32)
        h2 = rng.standard_normal(50).astype(np.float32)
        out_over = interpolate_rir_segment(h1, h2, alpha=1.5)
        out_1    = interpolate_rir_segment(h1, h2, alpha=1.0)
        np.testing.assert_array_almost_equal(out_over, out_1, decimal=5)

    def test_interpolate_different_lengths_zero_padded(self):
        """Shorter array zero-padded; output length = max(len_start, len_end)."""
        rng = np.random.default_rng(3)
        h1 = rng.standard_normal(100).astype(np.float32)
        h2 = rng.standard_normal(120).astype(np.float32)
        out = interpolate_rir_segment(h1, h2, alpha=0.5)
        assert len(out) == 120

    def test_interpolate_returns_float32(self):
        h1 = np.ones(10, dtype=np.float32)
        h2 = np.ones(10, dtype=np.float32)
        out = interpolate_rir_segment(h1, h2, alpha=0.5)
        assert out.dtype == np.float32

    def test_interpolate_midpoint_is_average(self):
        """alpha=0.5 → output = 0.5*(h1+h2) for same-length arrays."""
        h1 = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        h2 = np.array([3.0, 4.0, 5.0], dtype=np.float32)
        out = interpolate_rir_segment(h1, h2, alpha=0.5)
        expected = np.array([2.0, 3.0, 4.0], dtype=np.float32)
        np.testing.assert_array_almost_equal(out, expected, decimal=5)


# ---------------------------------------------------------------------------
# UF-W124-04: render_waveform
# ---------------------------------------------------------------------------

class TestRenderWaveform:
    def _make_simple_rir(self, n_rir: int = 500, fs: int = 16000) -> RIR:
        h = np.zeros(n_rir, dtype=np.float32)
        h[0] = 1.0  # Dirac
        return RIR(
            source_id="src0",
            receiver_id="mic0",
            h=h,
            fs=fs,
            rt60_measured_s=0.1,
            drr_db=40.0,
            peak_delay_samples=0,
        )

    def test_render_waveform_length_full(self):
        """mode='full': output length = len(source) + len(rir.h) - 1."""
        source = np.random.default_rng(0).standard_normal(1000).astype(np.float32)
        rir = self._make_simple_rir(n_rir=500)
        out = render_waveform(source, rir, mode="full")
        assert len(out) == 1000 + 500 - 1, (
            f"Expected length {1000 + 500 - 1}, got {len(out)}"
        )

    def test_render_waveform_length_same(self):
        """mode='same': output length = len(source)."""
        source = np.random.default_rng(1).standard_normal(1000).astype(np.float32)
        rir = self._make_simple_rir(n_rir=500)
        out = render_waveform(source, rir, mode="same")
        assert len(out) == 1000

    def test_render_waveform_length_ola(self):
        """mode='OLA': output length = len(source) + len(rir.h) - 1."""
        source = np.random.default_rng(2).standard_normal(1000).astype(np.float32)
        rir = self._make_simple_rir(n_rir=500)
        out = render_waveform(source, rir, mode="OLA")
        assert len(out) == 1000 + 500 - 1

    def test_render_waveform_ola_matches_full(self):
        """OLA convolution should match 'full' mode to within numerical tolerance."""
        source = np.random.default_rng(3).standard_normal(512).astype(np.float32)
        rir = self._make_simple_rir(n_rir=64)
        out_full = render_waveform(source, rir, mode="full")
        out_ola  = render_waveform(source, rir, mode="OLA")
        np.testing.assert_allclose(out_full, out_ola, atol=1e-4)

    def test_render_empty_source_raises(self):
        """Empty source_signal → ValueError."""
        empty = np.array([], dtype=np.float32)
        rir = self._make_simple_rir()
        with pytest.raises(ValueError):
            render_waveform(empty, rir, mode="full")

    def test_render_empty_rir_raises(self):
        """Empty rir.h → ValueError."""
        source = np.ones(100, dtype=np.float32)
        rir = RIR(
            source_id="s", receiver_id="m",
            h=np.array([], dtype=np.float32),
            fs=16000, rt60_measured_s=0.0, drr_db=0.0, peak_delay_samples=0,
        )
        with pytest.raises(ValueError):
            render_waveform(source, rir, mode="full")

    def test_render_invalid_mode_raises(self):
        """Unknown mode → ValueError."""
        source = np.ones(100, dtype=np.float32)
        rir = self._make_simple_rir()
        with pytest.raises(ValueError, match="mode"):
            render_waveform(source, rir, mode="invalid")

    def test_render_returns_float32(self):
        source = np.random.default_rng(4).standard_normal(200).astype(np.float32)
        rir = self._make_simple_rir()
        out = render_waveform(source, rir, mode="full")
        assert out.dtype == np.float32

    def test_render_dirac_rir_is_identity(self):
        """Convolving with a Dirac at sample 0 → output same as source (full mode)."""
        source = np.random.default_rng(5).standard_normal(100).astype(np.float32)
        h = np.zeros(50, dtype=np.float32)
        h[0] = 1.0
        rir = RIR(
            source_id="s", receiver_id="m",
            h=h, fs=16000,
            rt60_measured_s=0.0, drr_db=60.0, peak_delay_samples=0,
        )
        out = render_waveform(source, rir, mode="full")
        # First len(source) samples should equal source
        np.testing.assert_allclose(out[:len(source)], source, atol=1e-5)

    def test_render_waveform_all_modes_finite(self):
        """All output values should be finite."""
        source = np.random.default_rng(6).standard_normal(500).astype(np.float32)
        rir = self._make_simple_rir()
        for mode in ("full", "same", "OLA"):
            out = render_waveform(source, rir, mode=mode)
            assert np.all(np.isfinite(out)), f"Non-finite values in mode={mode}"


def test_rir_finite_short_rt60():
    """Audit F-01: empty late tail (mixing time ≥ RIR length) must not yield NaN."""
    dp = _make_direct_path(distance_m=2.0, fs=16000, attenuation=0.5)
    refl = _make_reflection_data(rt60_s=0.02, mixing_time_ms=600.0, seed=1)
    rir = generate_static_rir(dp, refl, _make_no_occlusion(), fs=16000)
    assert np.all(np.isfinite(rir.h))
    assert rir.peak_delay_samples == dp.delay_samples


def test_image_sources_never_precede_direct_path():
    """ISM images for a room spanning [0, L] are never closer than the direct path."""
    from simulator.uf.w122_reverberation import compute_image_sources
    src = np.array([1.0, 1.2, 1.3])
    mic = np.array([4.0, 1.5, 3.0])
    imgs = compute_image_sources({"L": 5.0, "W": 4.0, "H": 3.0}, src, mic, ism_order=2)
    d_direct = float(np.linalg.norm(src - mic))
    assert min(float(np.linalg.norm(i.position - mic)) for i in imgs) > d_direct
    # First-order images are mirror images across the six walls.
    first = sorted(tuple(np.round(i.position, 6)) for i in imgs if i.reflection_order == 1)
    expected = sorted([(-1.0, 1.2, 1.3), (9.0, 1.2, 1.3), (1.0, -1.2, 1.3),
                       (1.0, 4.8, 1.3), (1.0, 1.2, -1.3), (1.0, 1.2, 6.7)])
    assert first == expected
