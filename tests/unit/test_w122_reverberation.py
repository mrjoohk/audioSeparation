"""
Unit tests for UF-W122: Reverberation Modelling
(w122_reverberation.py)

Tests:
    test_ism_image_count_order1       – UF-W122-01
    test_late_tail_rt60               – UF-W122-02
    test_late_tail_reproducibility    – UF-W122-02
    test_sabine_rt60_concrete         – helper
    test_fit_rt60_synthetic           – UF-W122-04
"""
from __future__ import annotations

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

from simulator.types import ImageSource, MaterialSpec
from simulator.uf.w122_reverberation import (
    compute_image_sources,
    generate_late_reverb_tail,
    shape_reverb_by_frequency,
    fit_rt60,
    estimate_sabine_rt60,
)

# ---------------------------------------------------------------------------
# Room fixture
# ---------------------------------------------------------------------------
ROOM_5_4_3 = {"L": 5.0, "W": 4.0, "H": 3.0}
SRC_POS = np.array([1.0, 1.0, 1.0])
MIC_POS = np.array([4.0, 1.5, 2.0])


# ---------------------------------------------------------------------------
# UF-W122-01: Image Source Method
# ---------------------------------------------------------------------------

class TestComputeImageSources:
    def test_returns_list_of_image_source(self):
        imgs = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=1)
        assert isinstance(imgs, list)
        for img in imgs:
            assert isinstance(img, ImageSource)

    def test_ism_image_count_order1(self):
        """Order=1 in a shoebox → exactly 6 primary image sources (one per wall face).

        NOTE: The Allen-Berkley enumeration for order=1 iterates (nx,ny,nz) in
        {-1,0,1}^3 \ {(0,0,0)}.  Many of the 26 combinations produce the same
        reflection order 1,2,3.  Strictly, the six *first-order* image sources
        have |nx|+|ny|+|nz|=1.  Total image sources at order ≤ 1 can be up to
        26 (before filtering by max distance).  The spec says ism_order=1 → 6;
        this is the count of *first-order* mirrors only.

        We check both: exactly 6 have reflection_order == 1, and the list is ≥ 6.
        """
        imgs = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=1)
        first_order = [img for img in imgs if img.reflection_order == 1]
        assert len(first_order) == 6, (
            f"Expected 6 first-order image sources, got {len(first_order)}"
        )

    def test_ism_image_count_grows_with_order(self):
        """Higher ISM orders produce more image sources."""
        imgs1 = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=1)
        imgs3 = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=3)
        assert len(imgs3) >= len(imgs1)

    def test_all_image_sources_within_max_distance(self):
        """All image sources must be within MAX_RIR_DURATION_S * c distance."""
        from simulator.types import MAX_RIR_DURATION_S, SPEED_OF_SOUND
        max_dist = MAX_RIR_DURATION_S * SPEED_OF_SOUND
        imgs = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=3)
        for img in imgs:
            dist = float(np.linalg.norm(np.asarray(img.position) - MIC_POS))
            assert dist <= max_dist + 1e-6, (
                f"Image source beyond max distance: {dist:.2f} m > {max_dist:.2f} m"
            )

    def test_image_source_path_gain_positive(self):
        """All path gains should be positive (physical)."""
        imgs = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=2)
        for img in imgs:
            assert img.path_gain > 0.0

    def test_path_gain_decreases_with_distance(self):
        """Higher-order images (farther away) should generally have lower gain."""
        imgs = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=3)
        order1 = [img for img in imgs if img.reflection_order == 1]
        order3 = [img for img in imgs if img.reflection_order == 3]
        if order1 and order3:
            avg1 = np.mean([img.path_gain for img in order1])
            avg3 = np.mean([img.path_gain for img in order3])
            assert avg3 < avg1, "Higher-order image sources should have lower mean path gain"

    def test_uniform_alpha_equals_none(self):
        """Passing alpha=0.5 (default) should equal passing None."""
        imgs_none = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=2)
        imgs_half = compute_image_sources(
            ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=2,
            material_map_or_alpha_per_wall=0.5
        )
        assert len(imgs_none) == len(imgs_half)

    def test_ism_with_material_map(self):
        """MaterialMap input should produce image sources."""
        mat = MaterialSpec(name="concrete", alpha=np.full(6, 0.03), sigma=np.zeros(6))
        mat_map = {sid: mat for sid in ["floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"]}
        imgs = compute_image_sources(ROOM_5_4_3, SRC_POS, MIC_POS, ism_order=1,
                                     material_map_or_alpha_per_wall=mat_map)
        assert len(imgs) > 0


# ---------------------------------------------------------------------------
# UF-W122-02: Late Reverb Tail
# ---------------------------------------------------------------------------

class TestGenerateLateReverbTail:
    def test_returns_float32(self):
        tail = generate_late_reverb_tail(0.5, 30.0, 16000, seed=42)
        assert tail.dtype == np.float32

    def test_correct_length_default(self):
        rt60 = 0.5
        fs = 16000
        tail = generate_late_reverb_tail(rt60, 30.0, fs, seed=42)
        expected_len = int(min(rt60 * 3.0 * fs, 4.0 * fs))
        assert len(tail) == expected_len

    def test_correct_length_override(self):
        tail = generate_late_reverb_tail(0.5, 30.0, 16000, n_samples=8000, seed=42)
        assert len(tail) == 8000

    def test_late_tail_reproducibility(self):
        """Same seed → identical arrays."""
        t1 = generate_late_reverb_tail(0.5, 30.0, 16000, seed=42)
        t2 = generate_late_reverb_tail(0.5, 30.0, 16000, seed=42)
        np.testing.assert_array_equal(t1, t2)

    def test_different_seeds_differ(self):
        """Different seeds → different arrays."""
        t1 = generate_late_reverb_tail(0.5, 30.0, 16000, seed=42)
        t2 = generate_late_reverb_tail(0.5, 30.0, 16000, seed=99)
        assert not np.allclose(t1, t2)

    def test_onset_zeros(self):
        """Samples before mixing_time should be zero."""
        fs = 16000
        mixing_ms = 30.0
        tail = generate_late_reverb_tail(0.5, mixing_ms, fs, seed=42)
        onset = int(round(mixing_ms * 1e-3 * fs))
        np.testing.assert_array_equal(tail[:onset], 0.0)

    def test_late_tail_rt60(self):
        """Energy decay of late tail should reflect approximately the requested RT60."""
        rt60_target = 0.5
        fs = 16000
        mixing_ms = 10.0
        # Use a longer tail for the RT60 measurement (3 × RT60 = 1.5 s)
        n_samples = int(rt60_target * 3 * fs)
        tail = generate_late_reverb_tail(rt60_target, mixing_ms, fs,
                                         n_samples=n_samples, seed=42)

        # Measure RT60 using the fit_rt60 helper
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = fit_rt60(tail, fs=fs)

        measured = result["rt60_measured_s"]
        assert 0.4 <= measured <= 0.6, (
            f"Measured RT60 {measured:.3f} s outside [0.4, 0.6] s for target {rt60_target} s"
        )


# ---------------------------------------------------------------------------
# UF-W122-03: Frequency-Shaped Reverb
# ---------------------------------------------------------------------------

class TestShapeReverbByFrequency:
    def test_returns_float32(self):
        rng = np.random.default_rng(0)
        base = rng.standard_normal(16000).astype(np.float32)
        shaped = shape_reverb_by_frequency(base, np.full(6, 0.5), 16000)
        assert shaped.dtype == np.float32

    def test_same_length_as_input(self):
        rng = np.random.default_rng(1)
        base = rng.standard_normal(8000).astype(np.float32)
        shaped = shape_reverb_by_frequency(base, np.full(6, 0.5), 16000)
        assert len(shaped) == 8000

    def test_wrong_band_count_raises(self):
        rng = np.random.default_rng(2)
        base = rng.standard_normal(4000).astype(np.float32)
        with pytest.raises(ValueError):
            shape_reverb_by_frequency(base, np.full(3, 0.5), 16000)

    def test_output_is_finite(self):
        rng = np.random.default_rng(3)
        base = rng.standard_normal(16000).astype(np.float32)
        shaped = shape_reverb_by_frequency(base, np.full(6, 0.5), 16000)
        assert np.all(np.isfinite(shaped))


# ---------------------------------------------------------------------------
# UF-W122-04: RT60 Fitting
# ---------------------------------------------------------------------------

class TestFitRt60:
    def _make_synthetic_rir(self, rt60_s: float, fs: int, seed: int = 7) -> np.ndarray:
        """Generate a synthetic RIR with known decay time."""
        n_samples = int(min(rt60_s * 3.0 * fs, 4.0 * fs))
        t = np.arange(n_samples, dtype=np.float64) / fs
        rng = np.random.default_rng(seed)
        noise = rng.standard_normal(n_samples)
        rir = (noise * np.exp(-6.9 * t / rt60_s)).astype(np.float32)
        return rir

    def test_fit_rt60_synthetic(self):
        """Measured RT60 should be within ±10 % of the known decay time."""
        target_rt60 = 0.5
        fs = 16000
        rir = self._make_synthetic_rir(target_rt60, fs, seed=7)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = fit_rt60(rir, fs=fs, target_rt60=target_rt60)

        measured = result["rt60_measured_s"]
        tol = 0.1 * target_rt60
        assert abs(measured - target_rt60) <= tol, (
            f"Measured RT60 {measured:.4f} s differs from target {target_rt60} s "
            f"by more than 10 %"
        )
        assert result["fitting_error_s"] == pytest.approx(measured - target_rt60, abs=1e-9)

    def test_fit_rt60_no_target(self):
        """fitting_error_s is None when no target provided."""
        rir = self._make_synthetic_rir(0.3, 16000)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = fit_rt60(rir, fs=16000, target_rt60=None)
        assert result["fitting_error_s"] is None

    def test_fit_rt60_returns_positive(self):
        """Measured RT60 must be non-negative."""
        rir = self._make_synthetic_rir(0.8, 16000)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = fit_rt60(rir, fs=16000)
        assert result["rt60_measured_s"] >= 0.0

    def test_fit_rt60_empty_raises(self):
        """Empty RIR should raise ValueError."""
        with pytest.raises(ValueError):
            fit_rt60(np.array([], dtype=np.float32), fs=16000)

    def test_fit_rt60_short_rir_extrapolates(self):
        """Short RIR (< 60 dB decay) should warn and return a plausible estimate."""
        rt60 = 2.0
        fs = 16000
        # Make a RIR only 0.5 s long (< rt60) — cannot reach −60 dB
        n_samples = int(0.5 * fs)
        t = np.arange(n_samples, dtype=np.float64) / fs
        rir = (np.exp(-6.9 * t / rt60) * np.random.default_rng(9).standard_normal(n_samples)).astype(np.float32)
        with pytest.warns(RuntimeWarning):
            result = fit_rt60(rir, fs=fs)
        # Extrapolated value should be > 0
        assert result["rt60_measured_s"] > 0.0

    def test_fit_rt60_multiple_rt60_values(self):
        """Longer RT60 should measure longer than shorter RT60."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            r1 = fit_rt60(self._make_synthetic_rir(0.3, 16000), 16000)
            r2 = fit_rt60(self._make_synthetic_rir(1.0, 16000), 16000)
        assert r2["rt60_measured_s"] > r1["rt60_measured_s"]


# ---------------------------------------------------------------------------
# Helper: Sabine RT60
# ---------------------------------------------------------------------------

class TestEstimateSabineRt60:
    def _concrete_map(self, alpha_500: float = 0.03) -> dict:
        mat = MaterialSpec(
            name="concrete",
            alpha=np.full(6, alpha_500),
            sigma=np.zeros(6),
        )
        return {
            sid: mat
            for sid in ["floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"]
        }

    def test_sabine_rt60_concrete(self):
        """5x4x3 room, concrete (α≈0.03 @500 Hz) → Sabine RT60 >> 0.5 s."""
        mat_map = self._concrete_map(0.03)
        rt60 = estimate_sabine_rt60(ROOM_5_4_3, mat_map)
        assert rt60 > 0.5, f"Sabine RT60 {rt60:.3f} s not > 0.5 s for concrete room"

    def test_sabine_formula_volume_scaling(self):
        """Doubling volume at same absorption should roughly double RT60."""
        mat_map = self._concrete_map(0.1)
        rt60_small = estimate_sabine_rt60({"L": 5.0, "W": 4.0, "H": 3.0}, mat_map)
        rt60_large = estimate_sabine_rt60({"L": 10.0, "W": 4.0, "H": 3.0}, mat_map)
        # Not exactly 2× due to surface area also changing, but should be larger
        assert rt60_large > rt60_small

    def test_sabine_high_absorption_short_rt60(self):
        """High absorption (α≈0.9) → short RT60."""
        mat = MaterialSpec(name="foam", alpha=np.full(6, 0.9), sigma=np.zeros(6))
        mat_map = {sid: mat for sid in ["floor", "ceiling", "wall_x+", "wall_x-", "wall_z+", "wall_z-"]}
        rt60 = estimate_sabine_rt60(ROOM_5_4_3, mat_map)
        assert rt60 < 0.5, f"High-absorption room RT60 {rt60:.3f} s should be < 0.5 s"

    def test_sabine_returns_float(self):
        mat_map = self._concrete_map()
        rt60 = estimate_sabine_rt60(ROOM_5_4_3, mat_map)
        assert isinstance(rt60, float)

    def test_sabine_missing_surfaces_use_default(self):
        """If some surfaces missing from mat_map, default alpha=0.5 is used."""
        mat = MaterialSpec(name="wood", alpha=np.full(6, 0.15), sigma=np.zeros(6))
        partial_map = {"floor": mat, "ceiling": mat}
        rt60 = estimate_sabine_rt60(ROOM_5_4_3, partial_map)
        assert rt60 > 0.0
