"""
Unit tests for UF-W154: Visualization Utilities.

Tests:
  - test_room_layout_creates_file
  - test_rir_plot_creates_file
  - test_waveform_plot_4ch
  - test_rt60_comparison_creates_file
"""
from __future__ import annotations

import sys
import tempfile
import os
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent.parent
_SRC = _REPO_ROOT / "src"
for _p in (_SRC, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Force Agg before importing module under test (defensive; module also does it)
import matplotlib
matplotlib.use("Agg")

from simulator.uf.w154_visualization import (  # noqa: E402
    plot_room_layout,
    plot_rir_statistics,
    plot_rt60_comparison,
    plot_waveform_channels,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_rir(n_samples: int = 8000, decay_rate: float = 6.9) -> np.ndarray:
    """Return a synthetic exponentially-decaying noise RIR."""
    rng = np.random.default_rng(123)
    t = np.linspace(0, 1.0, n_samples)
    return np.exp(-decay_rate * t) * rng.standard_normal(n_samples)


def _room_dict():
    return {"L": 6.0, "W": 4.0, "H": 3.0}


def _sources():
    return [
        {"x": 1.5, "z": 1.5},
        {"x": 3.0, "z": 2.0},
    ]


def _receivers():
    return [{"x": 4.5, "z": 2.5}]


# ---------------------------------------------------------------------------
# Room layout tests
# ---------------------------------------------------------------------------


class TestPlotRoomLayout:

    def test_room_layout_creates_file(self):
        """plot_room_layout must create a PNG file at the given output_path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "room_layout.png")
            plot_room_layout(_room_dict(), _sources(), _receivers(), output_path=out)
            assert Path(out).exists(), f"PNG not created at {out}"
            assert Path(out).stat().st_size > 0, "PNG file is empty"

    def test_room_layout_with_obstacles(self):
        """plot_room_layout with obstacles must still produce a PNG."""
        obstacles = [{"x": 3.0, "z": 2.0, "w": 0.5, "d": 0.3}]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "room_obstacles.png")
            plot_room_layout(_room_dict(), _sources(), _receivers(),
                             obstacles=obstacles, output_path=out)
            assert Path(out).exists()

    def test_room_layout_no_output_path_uses_tempfile(self):
        """plot_room_layout(output_path=None) should warn and save to temp file."""
        import warnings as _warnings
        with _warnings.catch_warnings(record=True) as w:
            _warnings.simplefilter("always")
            plot_room_layout(_room_dict(), _sources(), _receivers(), output_path=None)
        # Should have warned about temp file usage
        messages = [str(warning.message) for warning in w]
        assert any("temp" in m.lower() or "None" in m or "tmp" in m.lower()
                   for m in messages), f"Expected tempfile warning, got: {messages}"

    def test_room_layout_empty_sources(self):
        """plot_room_layout with no sources must not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "empty_sources.png")
            plot_room_layout(_room_dict(), [], _receivers(), output_path=out)
            assert Path(out).exists()

    def test_room_layout_aabb_style(self):
        """Room bbox given as dict with nested 'dimensions' key should work."""
        room = {"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}}
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "room_aabb.png")
            plot_room_layout(room, _sources(), _receivers(), output_path=out)
            assert Path(out).exists()


# ---------------------------------------------------------------------------
# RIR statistics tests
# ---------------------------------------------------------------------------


class TestPlotRirStatistics:

    def test_rir_plot_creates_file(self):
        """plot_rir_statistics must create a PNG file for a valid RIR."""
        rir = _make_rir()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "rir_stats.png")
            plot_rir_statistics(rir, output_path=out)
            assert Path(out).exists(), f"RIR plot PNG not created at {out}"
            assert Path(out).stat().st_size > 0, "RIR plot PNG is empty"

    def test_rir_plot_short_rir(self):
        """Short RIR (< 1000 samples) must still produce a valid PNG."""
        rir = _make_rir(n_samples=100)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "rir_short.png")
            plot_rir_statistics(rir, output_path=out)
            assert Path(out).exists()

    def test_rir_plot_silent_signal(self):
        """All-zeros RIR must not raise (edge case for Schroeder)."""
        rir = np.zeros(4000)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "rir_silent.png")
            plot_rir_statistics(rir, output_path=out)
            assert Path(out).exists()

    def test_rir_plot_no_output_path(self):
        """plot_rir_statistics(output_path=None) should warn and not raise."""
        import warnings as _warnings
        rir = _make_rir(n_samples=500)
        with _warnings.catch_warnings(record=True) as w:
            _warnings.simplefilter("always")
            plot_rir_statistics(rir, output_path=None)
        assert len(w) >= 1


# ---------------------------------------------------------------------------
# Waveform channels tests
# ---------------------------------------------------------------------------


class TestPlotWaveformChannels:

    def test_waveform_plot_4ch(self):
        """4-channel signal must produce a PNG file."""
        rng = np.random.default_rng(0)
        signal = rng.standard_normal((4, 16000)).astype(np.float32)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "waveform_4ch.png")
            plot_waveform_channels(signal, [0, 1, 2, 3], fs=16000, output_path=out)
            assert Path(out).exists(), f"Waveform PNG not created at {out}"
            assert Path(out).stat().st_size > 0

    def test_waveform_plot_1ch(self):
        """Single-channel (1-D) signal must produce a valid PNG."""
        rng = np.random.default_rng(1)
        signal = rng.standard_normal(8000)
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "waveform_1ch.png")
            plot_waveform_channels(signal, ["mono"], fs=8000, output_path=out)
            assert Path(out).exists()

    def test_waveform_plot_warns_above_8ch(self):
        """More than 8 channels must produce a UserWarning."""
        import warnings as _warnings
        rng = np.random.default_rng(2)
        signal = rng.standard_normal((10, 4000)).astype(np.float32)
        channel_ids = list(range(10))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "waveform_10ch.png")
            with _warnings.catch_warnings(record=True) as w:
                _warnings.simplefilter("always")
                plot_waveform_channels(signal, channel_ids, fs=16000, output_path=out)
            assert any(issubclass(warning.category, UserWarning) for warning in w), (
                "Expected UserWarning for > 8 channels"
            )
            assert Path(out).exists()

    def test_waveform_plot_string_channel_ids(self):
        """String channel labels should be accepted."""
        rng = np.random.default_rng(3)
        signal = rng.standard_normal((2, 4000))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "waveform_str_ch.png")
            plot_waveform_channels(signal, ["left", "right"], fs=44100, output_path=out)
            assert Path(out).exists()


# ---------------------------------------------------------------------------
# RT60 comparison tests
# ---------------------------------------------------------------------------


class TestPlotRt60Comparison:

    def test_rt60_comparison_creates_file(self):
        """plot_rt60_comparison must create a PNG for standard 6-band RT60 list."""
        rt60_bands = [0.55, 0.52, 0.48, 0.43, 0.38, 0.35]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "rt60_comparison.png")
            plot_rt60_comparison(rt60_bands, output_path=out)
            assert Path(out).exists(), f"RT60 comparison PNG not created at {out}"
            assert Path(out).stat().st_size > 0

    def test_rt60_comparison_with_sabine(self):
        """Sabine estimate line should be rendered without error."""
        rt60_bands = [0.55, 0.52, 0.48, 0.43, 0.38, 0.35]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "rt60_sabine.png")
            plot_rt60_comparison(rt60_bands, sabine_rt60=0.50, output_path=out)
            assert Path(out).exists()

    def test_rt60_comparison_custom_bands(self):
        """Custom band_centers should override default labels."""
        rt60_bands = [0.6, 0.5, 0.4]
        band_centers = [250.0, 500.0, 1000.0]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "rt60_custom.png")
            plot_rt60_comparison(rt60_bands, band_centers=band_centers, output_path=out)
            assert Path(out).exists()

    def test_rt60_comparison_single_band(self):
        """A single-band RT60 list must not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "rt60_1band.png")
            plot_rt60_comparison([0.4], output_path=out)
            assert Path(out).exists()
