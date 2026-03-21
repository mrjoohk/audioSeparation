"""
Unit tests for UF-W121: Direct Path Acoustic Propagation
(w121_direct_path.py)

Tests:
    test_delay_at_1m              – UF-W121-01
    test_attenuation_at_5m        – UF-W121-02
    test_doa_right_side           – UF-W121-03
    test_doa_zero_distance_raises – UF-W121-03
    test_air_attenuation_1khz     – UF-W121-04
    test_doppler_stationary       – UF-W121-04
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup — resolve src so imports work regardless of cwd
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from simulator.uf.w121_direct_path import (
    compute_distance_and_delay,
    compute_attenuation,
    compute_doa,
    compute_air_attenuation,
    build_direct_path,
)


# ---------------------------------------------------------------------------
# UF-W121-01: Distance and Delay
# ---------------------------------------------------------------------------

class TestDistanceAndDelay:
    def test_delay_at_1m(self):
        """src=(1,0,0), mic=(0,0,0), fs=16000 → distance=1.0, delay≈47 samples."""
        src = np.array([1.0, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        result = compute_distance_and_delay(src, mic, c=343.0, fs=16000)

        assert result["distance_m"] == pytest.approx(1.0, abs=1e-9)
        # 1 / 343 * 16000 = 46.647 → round to 47
        assert result["delay_samples"] in (46, 47), (
            f"Expected delay_samples 46 or 47, got {result['delay_samples']}"
        )
        assert result["delay_s"] == pytest.approx(1.0 / 343.0, rel=1e-6)

    def test_distance_diagonal(self):
        """3-4-5 Pythagorean triple."""
        src = np.array([3.0, 4.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        result = compute_distance_and_delay(src, mic, c=343.0, fs=16000)
        assert result["distance_m"] == pytest.approx(5.0, abs=1e-9)

    def test_near_field_warning(self):
        """Distance < 0.1 m should emit a RuntimeWarning."""
        src = np.array([0.05, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        with pytest.warns(RuntimeWarning, match="Near-field"):
            compute_distance_and_delay(src, mic, fs=16000)

    def test_far_field_warning(self):
        """Distance > 25 m should emit a RuntimeWarning."""
        src = np.array([30.0, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        with pytest.warns(RuntimeWarning, match="Far-field"):
            compute_distance_and_delay(src, mic, fs=16000)

    def test_zero_delay_coincident_positions(self):
        """Coincident positions → distance=0, delay_samples=0 (with near-field warning)."""
        src = np.array([1.0, 1.0, 1.0])
        mic = np.array([1.0, 1.0, 1.0])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            result = compute_distance_and_delay(src, mic, fs=16000)
        assert result["distance_m"] == pytest.approx(0.0, abs=1e-9)
        assert result["delay_samples"] == 0


# ---------------------------------------------------------------------------
# UF-W121-02: Attenuation
# ---------------------------------------------------------------------------

class TestAttenuation:
    def test_attenuation_at_1m(self):
        """At ref distance attenuation should be 1.0."""
        assert compute_attenuation(1.0, ref_distance_m=1.0) == pytest.approx(1.0, abs=1e-9)

    def test_attenuation_at_5m(self):
        """d=5.0, ref=1.0 → attenuation = 0.2."""
        result = compute_attenuation(5.0, ref_distance_m=1.0)
        assert result == pytest.approx(0.2, abs=0.001)

    def test_attenuation_near_field_cap(self):
        """Distance < ref → attenuation clamped to 1.0 (not above unity)."""
        result = compute_attenuation(0.1, ref_distance_m=1.0)
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_attenuation_very_small_distance(self):
        """Distance=0 → safe minimum used (0.01 m) → attenuation=1.0 (clamped)."""
        result = compute_attenuation(0.0, ref_distance_m=1.0)
        assert 0.0 <= result <= 1.0

    def test_attenuation_at_10m(self):
        """d=10.0, ref=1.0 → 0.1."""
        assert compute_attenuation(10.0, ref_distance_m=1.0) == pytest.approx(0.1, abs=1e-9)


# ---------------------------------------------------------------------------
# UF-W121-03: Direction of Arrival
# ---------------------------------------------------------------------------

class TestDOA:
    def test_doa_right_side(self):
        """Source at (+5,0,0), mic at origin → az≈π/2, el≈0."""
        src = np.array([5.0, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        result = compute_doa(src, mic)
        assert result["doa_az_rad"] == pytest.approx(math.pi / 2.0, abs=0.01)
        assert result["doa_el_rad"] == pytest.approx(0.0, abs=0.01)

    def test_doa_left_side(self):
        """Source at (-5,0,0) → az≈-π/2."""
        src = np.array([-5.0, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        result = compute_doa(src, mic)
        assert result["doa_az_rad"] == pytest.approx(-math.pi / 2.0, abs=0.01)

    def test_doa_directly_in_front(self):
        """Source at (0,0,+5) → az≈0, el≈0 (Y-up convention, Z is forward)."""
        src = np.array([0.0, 0.0, 5.0])
        mic = np.array([0.0, 0.0, 0.0])
        result = compute_doa(src, mic)
        assert result["doa_az_rad"] == pytest.approx(0.0, abs=0.01)
        assert result["doa_el_rad"] == pytest.approx(0.0, abs=0.01)

    def test_doa_above(self):
        """Source directly above → el≈+π/2."""
        src = np.array([0.0, 5.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        result = compute_doa(src, mic)
        assert result["doa_el_rad"] == pytest.approx(math.pi / 2.0, abs=0.01)

    def test_doa_zero_distance_raises(self):
        """src_pos == mic_pos → ValueError."""
        src = np.array([1.0, 2.0, 3.0])
        mic = np.array([1.0, 2.0, 3.0])
        with pytest.raises(ValueError, match="zero distance"):
            compute_doa(src, mic)

    def test_doa_with_identity_quaternion(self):
        """Identity quaternion → same result as no quaternion."""
        src = np.array([5.0, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        q_id = np.array([0.0, 0.0, 0.0, 1.0])  # identity (x,y,z,w)
        result_no_quat = compute_doa(src, mic, mic_orientation_quat=None)
        result_with_quat = compute_doa(src, mic, mic_orientation_quat=q_id)
        assert result_no_quat["doa_az_rad"] == pytest.approx(
            result_with_quat["doa_az_rad"], abs=0.01
        )
        assert result_no_quat["doa_el_rad"] == pytest.approx(
            result_with_quat["doa_el_rad"], abs=0.01
        )

    def test_doa_azimuth_range(self):
        """Azimuth must be in [-π, π]."""
        rng = np.random.default_rng(99)
        for _ in range(20):
            src = rng.uniform(-5.0, 5.0, 3)
            mic = rng.uniform(-5.0, 5.0, 3)
            if np.linalg.norm(src - mic) < 0.1:
                continue
            result = compute_doa(src, mic)
            assert -math.pi - 0.01 <= result["doa_az_rad"] <= math.pi + 0.01
            assert -math.pi / 2 - 0.01 <= result["doa_el_rad"] <= math.pi / 2 + 0.01


# ---------------------------------------------------------------------------
# UF-W121-04: Air Attenuation
# ---------------------------------------------------------------------------

class TestAirAttenuation:
    def test_air_attenuation_1khz(self):
        """d=10 m, f=1000 Hz → air_atten_db ≈ 0.038 dB (ISO 9613-1)."""
        result = compute_air_attenuation(10.0, 1000.0)
        assert result["air_atten_db"] == pytest.approx(0.038, abs=0.005)

    def test_air_attenuation_at_125hz(self):
        """d=10 m, f=125 Hz → 0.003 dB."""
        result = compute_air_attenuation(10.0, 125.0)
        assert result["air_atten_db"] == pytest.approx(0.003, abs=0.001)

    def test_air_attenuation_at_4khz(self):
        """d=10 m, f=4000 Hz → 0.36 dB."""
        result = compute_air_attenuation(10.0, 4000.0)
        assert result["air_atten_db"] == pytest.approx(0.360, abs=0.01)

    def test_doppler_stationary(self):
        """velocity=0 → doppler_factor=1.0."""
        result = compute_air_attenuation(5.0, 1000.0, velocity_radial_m_s=0.0)
        assert result["doppler_factor"] == pytest.approx(1.0, abs=1e-9)

    def test_doppler_approaching(self):
        """Positive velocity (approaching) → doppler_factor > 1.0."""
        result = compute_air_attenuation(5.0, 1000.0, velocity_radial_m_s=34.3)
        assert result["doppler_factor"] > 1.0

    def test_doppler_receding(self):
        """Negative velocity (receding) → doppler_factor < 1.0."""
        result = compute_air_attenuation(5.0, 1000.0, velocity_radial_m_s=-34.3)
        assert result["doppler_factor"] < 1.0

    def test_high_velocity_warns(self):
        """Velocity > 10% of c → RuntimeWarning."""
        with pytest.warns(RuntimeWarning, match="Radial velocity"):
            compute_air_attenuation(5.0, 1000.0, velocity_radial_m_s=100.0)

    def test_zero_freq_raises(self):
        """freq_hz=0 → ValueError."""
        with pytest.raises(ValueError):
            compute_air_attenuation(5.0, 0.0)

    def test_negative_freq_raises(self):
        """freq_hz<0 → ValueError."""
        with pytest.raises(ValueError):
            compute_air_attenuation(5.0, -500.0)

    def test_attenuation_increases_with_distance(self):
        """Air absorption should increase with distance."""
        r1 = compute_air_attenuation(5.0,  1000.0)["air_atten_db"]
        r2 = compute_air_attenuation(10.0, 1000.0)["air_atten_db"]
        assert r2 > r1

    def test_attenuation_increases_with_frequency(self):
        """Higher frequencies have more air absorption."""
        r1 = compute_air_attenuation(10.0,  500.0)["air_atten_db"]
        r2 = compute_air_attenuation(10.0, 4000.0)["air_atten_db"]
        assert r2 > r1


# ---------------------------------------------------------------------------
# Integration: build_direct_path
# ---------------------------------------------------------------------------

class TestBuildDirectPath:
    def test_build_direct_path_returns_direct_path(self):
        """build_direct_path assembles a DirectPath dataclass."""
        from simulator.types import DirectPath
        src = np.array([1.0, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        dp = build_direct_path("src0", "mic0", src, mic, fs=16000)
        assert isinstance(dp, DirectPath)
        assert dp.source_id == "src0"
        assert dp.receiver_id == "mic0"
        assert dp.distance_m == pytest.approx(1.0, abs=1e-9)
        assert dp.attenuation_linear == pytest.approx(1.0, abs=1e-9)
        assert dp.doppler_factor == pytest.approx(1.0, abs=1e-9)

    def test_build_direct_path_doa_right(self):
        """DOA is correct in the assembled DirectPath."""
        src = np.array([5.0, 0.0, 0.0])
        mic = np.array([0.0, 0.0, 0.0])
        dp = build_direct_path("s", "m", src, mic, fs=16000)
        assert dp.doa_az_rad == pytest.approx(math.pi / 2.0, abs=0.01)
        assert dp.doa_el_rad == pytest.approx(0.0, abs=0.01)
