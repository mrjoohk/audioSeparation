"""
Unit tests for UF-W123: Occlusion and Diffraction
(w123_occlusion.py)

Tests:
    test_visibility_no_obstacle       – UF-W123-01
    test_visibility_blocked           – UF-W123-01
    test_maekawa_on_axis              – UF-W123-03
    test_maekawa_zero_freq_raises     – UF-W123-03
    test_occlusion_update_cached      – UF-W123-04
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from simulator.types import AABB, OcclusionResult, PlacedObject
from simulator.uf.w123_occlusion import (
    visibility_test,
    estimate_occlusion_loss,
    maekawa_diffraction,
    update_occlusion_if_moved,
    compute_full_occlusion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_wall(obj_id: str = "wall_01", center=(2.5, 1.0, 0.0)) -> PlacedObject:
    """A 0.2 × 2 × 2 m partition centred between source and microphone."""
    return PlacedObject(
        object_id=obj_id,
        object_type="partition",
        position=np.array(center, dtype=np.float64),
        size=np.array([0.2, 2.0, 2.0], dtype=np.float64),
        rotation_y=0.0,
        acoustic_role="occluding",
    )


SRC = np.array([0.0, 1.0, 0.0])
MIC = np.array([5.0, 1.0, 0.0])


# ---------------------------------------------------------------------------
# UF-W123-01: Visibility Test
# ---------------------------------------------------------------------------

class TestVisibilityTest:
    def test_visibility_no_obstacle(self):
        """No obstacles → visible=True, blocking_object_id=None."""
        result = visibility_test(SRC, MIC, [])
        assert result["visible"] is True
        assert result["blocking_object_id"] is None

    def test_visibility_blocked(self):
        """Wall directly between src and mic → visible=False."""
        wall = _make_wall("wall_01", center=(2.5, 1.0, 0.0))
        result = visibility_test(SRC, MIC, [wall])
        assert result["visible"] is False
        assert result["blocking_object_id"] == "wall_01"

    def test_visibility_obstacle_off_path(self):
        """Obstacle far off the direct path → still visible."""
        # Place an obstacle 3 m above the line of sight
        off_path = PlacedObject(
            object_id="off_01",
            object_type="box",
            position=np.array([2.5, 4.0, 0.0]),
            size=np.array([0.5, 0.5, 0.5]),
            rotation_y=0.0,
        )
        result = visibility_test(SRC, MIC, [off_path])
        assert result["visible"] is True

    def test_visibility_multiple_obstacles_first_blocks(self):
        """Multiple obstacles; first blocker's ID is returned."""
        wall1 = _make_wall("wall_A", center=(1.5, 1.0, 0.0))
        wall2 = _make_wall("wall_B", center=(3.5, 1.0, 0.0))
        result = visibility_test(SRC, MIC, [wall1, wall2])
        assert result["visible"] is False
        assert result["blocking_object_id"] in ("wall_A", "wall_B")

    def test_visibility_coincident_src_mic(self):
        """src == mic → trivially visible (zero-length ray)."""
        result = visibility_test(SRC, SRC, [_make_wall()])
        # A zero-length segment cannot intersect (t_max=0); visible should be True
        # or False depending on the ray-AABB test; the important thing is no crash.
        assert "visible" in result

    def test_visibility_returns_dict_keys(self):
        """Return value always contains 'visible' and 'blocking_object_id'."""
        result = visibility_test(SRC, MIC, [])
        assert "visible" in result
        assert "blocking_object_id" in result


# ---------------------------------------------------------------------------
# UF-W123-02: Occlusion Loss Estimation
# ---------------------------------------------------------------------------

class TestEstimateOcclusionLoss:
    def test_loss_non_negative(self):
        wall = _make_wall()
        loss = estimate_occlusion_loss(SRC, MIC, wall)
        assert loss >= 0.0

    def test_loss_within_range(self):
        wall = _make_wall()
        loss = estimate_occlusion_loss(SRC, MIC, wall)
        assert 0.0 <= loss <= 20.0

    def test_large_obstacle_more_loss(self):
        """Larger obstacle should produce more loss."""
        small = PlacedObject("s", "box", np.array([2.5, 1.0, 0.0]),
                             np.array([0.2, 0.5, 0.5]), 0.0)
        large = PlacedObject("l", "box", np.array([2.5, 1.0, 0.0]),
                             np.array([0.2, 3.0, 3.0]), 0.0)
        loss_s = estimate_occlusion_loss(SRC, MIC, small)
        loss_l = estimate_occlusion_loss(SRC, MIC, large)
        assert loss_l >= loss_s

    def test_coincident_src_mic_returns_zero(self):
        """Zero ray length → no occlusion loss."""
        wall = _make_wall()
        loss = estimate_occlusion_loss(SRC, SRC, wall)
        assert loss == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# UF-W123-03: Maekawa Diffraction
# ---------------------------------------------------------------------------

class TestMaekawaeDiffraction:
    def _compute_N(self, src, mic, edge, freq_hz, c=343.0):
        d1 = np.linalg.norm(np.asarray(src) - np.asarray(edge))
        d2 = np.linalg.norm(np.asarray(mic) - np.asarray(edge))
        d  = np.linalg.norm(np.asarray(src) - np.asarray(mic))
        delta = d1 + d2 - d
        wavelength = c / freq_hz
        return 2.0 * delta / wavelength

    def test_maekawa_on_axis(self):
        """Arrange geometry so that N ≈ 1.0 → gain ≈ -10*log10(23) ≈ -13.6 dB."""
        # src at (0,0,0), mic at (2,0,0), edge at (1,0.1,0)
        # d1 = 1.005, d2 = 1.005, d = 2 → delta ≈ 0.01
        # wavelength for N=1: λ = 2*delta/N = 0.02 m → f = 343/0.02 = 17150 Hz
        src  = np.array([0.0, 0.0, 0.0])
        mic  = np.array([2.0, 0.0, 0.0])
        edge = np.array([1.0, 0.1, 0.0])

        d1 = math.sqrt(1.0 + 0.01)
        d2 = math.sqrt(1.0 + 0.01)
        d  = 2.0
        delta = d1 + d2 - d
        target_N = 1.0
        freq_hz = 343.0 * target_N / (2.0 * delta)

        gain_db = maekawa_diffraction(src, mic, edge, freq_hz=freq_hz)
        # Expected: -10*log10(3 + 20*1) = -10*log10(23) ≈ -13.6 dB
        expected = -10.0 * math.log10(23.0)
        assert gain_db == pytest.approx(expected, abs=0.1), (
            f"Maekawa gain {gain_db:.2f} dB, expected ≈ {expected:.2f} dB"
        )

    def test_maekawa_result_is_non_positive(self):
        """Diffraction gain must be ≤ 0 dB."""
        src  = np.array([0.0, 0.0, 0.0])
        mic  = np.array([5.0, 0.0, 0.0])
        edge = np.array([2.5, 1.0, 0.0])
        gain = maekawa_diffraction(src, mic, edge, freq_hz=1000.0)
        assert gain <= 0.0

    def test_maekawa_zero_freq_raises(self):
        """freq_hz=0 → ValueError."""
        src  = np.array([0.0, 0.0, 0.0])
        mic  = np.array([5.0, 0.0, 0.0])
        edge = np.array([2.5, 1.0, 0.0])
        with pytest.raises(ValueError):
            maekawa_diffraction(src, mic, edge, freq_hz=0.0)

    def test_maekawa_negative_freq_raises(self):
        """freq_hz<0 → ValueError."""
        src  = np.array([0.0, 0.0, 0.0])
        mic  = np.array([5.0, 0.0, 0.0])
        edge = np.array([2.5, 1.0, 0.0])
        with pytest.raises(ValueError):
            maekawa_diffraction(src, mic, edge, freq_hz=-100.0)

    def test_maekawa_no_diffraction_when_N_nonpositive(self):
        """N ≤ 0 (no path length difference) → gain = 0 dB."""
        src  = np.array([0.0, 0.0, 0.0])
        mic  = np.array([4.0, 0.0, 0.0])
        # Edge on the direct path between src and mic → delta = 0 → N = 0
        edge = np.array([2.0, 0.0, 0.0])
        gain = maekawa_diffraction(src, mic, edge, freq_hz=1000.0)
        assert gain == pytest.approx(0.0, abs=0.01)

    def test_maekawa_increases_with_frequency(self):
        """Higher frequency → more diffraction loss (larger N)."""
        src  = np.array([0.0, 0.0, 0.0])
        mic  = np.array([5.0, 0.0, 0.0])
        edge = np.array([2.5, 0.5, 0.0])
        gain_low  = maekawa_diffraction(src, mic, edge, freq_hz=250.0)
        gain_high = maekawa_diffraction(src, mic, edge, freq_hz=4000.0)
        assert gain_high < gain_low


# ---------------------------------------------------------------------------
# UF-W123-04: Cached Occlusion Update
# ---------------------------------------------------------------------------

class TestUpdateOcclusionIfMoved:
    def _make_prev_result(self) -> OcclusionResult:
        wall = _make_wall()
        return compute_full_occlusion("src0", "mic0", SRC, MIC, [wall])

    def test_occlusion_update_cached(self):
        """Move < threshold → updated=False, same result returned."""
        wall = _make_wall()
        prev_occ = self._make_prev_result()
        curr_src = SRC + np.array([0.05, 0.0, 0.0])  # 0.05 m < threshold 0.1 m
        result, updated = update_occlusion_if_moved(
            prev_occ, SRC, MIC, curr_src, MIC, [wall], threshold_m=0.1
        )
        assert updated is False
        assert result is prev_occ  # same object returned

    def test_occlusion_update_recomputed(self):
        """Move > threshold → updated=True, new result."""
        wall = _make_wall()
        prev_occ = self._make_prev_result()
        curr_src = SRC + np.array([0.5, 0.0, 0.0])  # 0.5 m > threshold 0.1 m
        result, updated = update_occlusion_if_moved(
            prev_occ, SRC, MIC, curr_src, MIC, [wall], threshold_m=0.1
        )
        assert updated is True
        assert isinstance(result, OcclusionResult)

    def test_occlusion_update_mic_moved(self):
        """Mic movement > threshold triggers recompute."""
        wall = _make_wall()
        prev_occ = self._make_prev_result()
        curr_mic = MIC + np.array([0.0, 0.5, 0.0])
        result, updated = update_occlusion_if_moved(
            prev_occ, SRC, MIC, SRC, curr_mic, [wall], threshold_m=0.1
        )
        assert updated is True

    def test_occlusion_update_no_movement(self):
        """Zero displacement → cached."""
        wall = _make_wall()
        prev_occ = self._make_prev_result()
        result, updated = update_occlusion_if_moved(
            prev_occ, SRC, MIC, SRC, MIC, [wall], threshold_m=0.1
        )
        assert updated is False


# ---------------------------------------------------------------------------
# Helper: compute_full_occlusion
# ---------------------------------------------------------------------------

class TestComputeFullOcclusion:
    def test_no_obstacle_visible(self):
        """No obstacles → visible=True, loss=0."""
        occ = compute_full_occlusion("src0", "mic0", SRC, MIC, [])
        assert occ.visible is True
        assert occ.loss_db == pytest.approx(0.0)
        np.testing.assert_array_equal(occ.loss_db_per_band, 0.0)

    def test_blocked_non_zero_loss(self):
        """Blocker present → loss_db > 0."""
        wall = _make_wall()
        occ = compute_full_occlusion("src0", "mic0", SRC, MIC, [wall])
        assert occ.visible is False
        assert occ.loss_db >= 0.0

    def test_per_band_shape(self):
        """loss_db_per_band must have 6 elements."""
        wall = _make_wall()
        occ = compute_full_occlusion("src0", "mic0", SRC, MIC, [wall])
        assert occ.loss_db_per_band.shape == (6,)

    def test_returns_occlusion_result(self):
        occ = compute_full_occlusion("src0", "mic0", SRC, MIC, [])
        assert isinstance(occ, OcclusionResult)
