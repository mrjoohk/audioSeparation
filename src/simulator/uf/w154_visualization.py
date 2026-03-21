"""
UF-W154: Visualization Utilities for the Spatial Simulator.

Implements UF-W154-01 through UF-W154-04:
  - plot_room_layout      — 2-D top-down XZ room view
  - plot_rir_statistics   — RIR waveform + Schroeder energy decay
  - plot_waveform_channels — per-channel time-domain waveform
  - plot_rt60_comparison  — octave-band RT60 bar chart

IMPORTANT: Agg (non-interactive) backend is forced before any pyplot import.
"""
from __future__ import annotations

import sys
import tempfile
import warnings
from pathlib import Path
from typing import List, Optional, Sequence, Union

# ---------------------------------------------------------------------------
# Force non-interactive matplotlib backend BEFORE any pyplot import
# ---------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402  (must come after use())
import matplotlib.patches as mpatches  # noqa: E402
import numpy as np

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_SRC = _HERE.parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_DEFAULT_BAND_LABELS = ["125 Hz", "250 Hz", "500 Hz", "1 kHz", "2 kHz", "4 kHz"]
_MAX_CHANNELS_SHOWN = 8


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _save_or_show(fig: plt.Figure, output_path: Optional[str]) -> None:
    """Save figure to *output_path* (PNG) or, if None, save to a temp file
    (headless environment — displaying is not possible with Agg backend)."""
    if output_path is not None:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
    else:
        with tempfile.NamedTemporaryFile(
            suffix=".png", delete=False, prefix="simulator_plot_"
        ) as tmp:
            fig.savefig(tmp.name, dpi=150, bbox_inches="tight")
            warnings.warn(
                f"output_path is None; plot saved to temporary file: {tmp.name}",
                UserWarning,
                stacklevel=3,
            )
    plt.close(fig)


# ---------------------------------------------------------------------------
# UF-W154-01: Room layout (2-D top-down XZ)
# ---------------------------------------------------------------------------


def plot_room_layout(
    room_bbox: Union[dict, object],
    sources: List[Union[dict, object]],
    receivers: List[Union[dict, object]],
    obstacles: Optional[List[Union[dict, object]]] = None,
    output_path: Optional[str] = None,
) -> None:
    """Render a 2-D (top-down) XZ floor-plan of the room.

    Args:
        room_bbox:   Room bounding box.  Accepts:
                     - A dict with keys ``x``, ``z``, ``width`` (X extent),
                       ``depth`` (Z extent).
                     - An AABB object (``min_corner``, ``max_corner``).
                     - A dict with keys ``L`` (length/X) and ``W`` (width/Z)
                       (treated as origin at 0,0).
        sources:     List of source positions.  Each item may be:
                     - A dict with ``x`` and ``z`` keys (or ``position`` sub-dict).
                     - Any object with a ``.position`` attribute (numpy float[3]).
        receivers:   Same format as *sources*.
        obstacles:   Optional list of obstacles.  Each item may be:
                     - A dict with ``x``, ``z``, ``w`` (X size), ``d`` (Z size).
                     - A PlacedObject with ``.aabb`` property.
        output_path: PNG save path.  If None a temporary file is used.

    Must complete in < 5 s.
    """
    fig, ax = plt.subplots(figsize=(7, 6))

    # ---- Room rectangle ----
    def _room_rect():
        """Return (x0, z0, width, depth) from room_bbox."""
        if isinstance(room_bbox, dict):
            if "L" in room_bbox and "W" in room_bbox:
                return 0.0, 0.0, float(room_bbox["L"]), float(room_bbox["W"])
            if "dimensions" in room_bbox:
                dims = room_bbox["dimensions"]
                return 0.0, 0.0, float(dims.get("L", dims.get("x", 1.0))), \
                                  float(dims.get("W", dims.get("z", 1.0)))
            return (
                float(room_bbox.get("x", 0.0)),
                float(room_bbox.get("z", 0.0)),
                float(room_bbox.get("width", room_bbox.get("L", 5.0))),
                float(room_bbox.get("depth", room_bbox.get("W", 4.0))),
            )
        # Assume AABB-like object
        try:
            mn = room_bbox.min_corner
            mx = room_bbox.max_corner
            return float(mn[0]), float(mn[2]), float(mx[0] - mn[0]), float(mx[2] - mn[2])
        except AttributeError:
            return 0.0, 0.0, 5.0, 4.0

    rx0, rz0, rw, rd = _room_rect()
    room_patch = mpatches.Rectangle(
        (rx0, rz0), rw, rd,
        linewidth=2, edgecolor="black", facecolor="#f5f5f5", zorder=1,
    )
    ax.add_patch(room_patch)

    # ---- Extract XZ position ----
    def _xz(item) -> tuple:
        """Return (x, z) float pair from a source/receiver item."""
        if isinstance(item, dict):
            if "position" in item and isinstance(item["position"], dict):
                p = item["position"]
                return float(p.get("x", 0.0)), float(p.get("z", 0.0))
            return float(item.get("x", 0.0)), float(item.get("z", 0.0))
        # numpy position array [x, y, z]
        try:
            pos = item.position
            return float(pos[0]), float(pos[2])
        except AttributeError:
            pass
        try:
            return float(item[0]), float(item[2])
        except (TypeError, IndexError):
            return 0.0, 0.0

    # ---- Sources (red stars) ----
    for src in sources:
        sx, sz = _xz(src)
        ax.plot(sx, sz, marker="*", color="red", markersize=14,
                label="Source", zorder=4, linestyle="None")

    # ---- Receivers (blue triangles) ----
    for rec in receivers:
        rx, rz = _xz(rec)
        ax.plot(rx, rz, marker="^", color="blue", markersize=10,
                label="Receiver", zorder=4, linestyle="None")

    # ---- Obstacles (gray filled boxes) ----
    if obstacles:
        for obs in obstacles:
            if isinstance(obs, dict):
                ox = float(obs.get("x", 0.0))
                oz = float(obs.get("z", 0.0))
                ow = float(obs.get("w", obs.get("width", 0.5)))
                od = float(obs.get("d", obs.get("depth", 0.5)))
                corner_x = ox - ow / 2
                corner_z = oz - od / 2
            else:
                try:
                    aabb = obs.aabb
                    mn = aabb.min_corner
                    mx = aabb.max_corner
                    corner_x = float(mn[0])
                    corner_z = float(mn[2])
                    ow = float(mx[0] - mn[0])
                    od = float(mx[2] - mn[2])
                except AttributeError:
                    corner_x, corner_z, ow, od = 0.0, 0.0, 0.5, 0.5
            obs_patch = mpatches.Rectangle(
                (corner_x, corner_z), ow, od,
                linewidth=1, edgecolor="gray", facecolor="lightgray",
                alpha=0.7, zorder=2,
            )
            ax.add_patch(obs_patch)

    # ---- Axes formatting ----
    margin = max(rw, rd) * 0.1 + 0.2
    ax.set_xlim(rx0 - margin, rx0 + rw + margin)
    ax.set_ylim(rz0 - margin, rz0 + rd + margin)
    ax.set_aspect("equal")
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Z (m)")
    ax.set_title("Room Layout (top-down XZ view)")
    ax.grid(True, linestyle="--", alpha=0.4)

    # Deduplicated legend
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    if by_label:
        ax.legend(by_label.values(), by_label.keys(), loc="upper right")

    _save_or_show(fig, output_path)


# ---------------------------------------------------------------------------
# UF-W154-02: RIR statistics
# ---------------------------------------------------------------------------


def _schroeder_decay(h: np.ndarray) -> np.ndarray:
    """Compute Schroeder backward integration (energy decay curve) in dB.

    EDC[n] = 10 * log10( sum_{k=n}^{N-1} h[k]^2 / sum_{k=0}^{N-1} h[k]^2 )
    """
    energy = h.astype(np.float64) ** 2
    total = np.sum(energy)
    if total == 0.0:
        return np.full(len(h), -np.inf)
    # Backward cumulative sum
    backward_cum = np.cumsum(energy[::-1])[::-1]
    edc = 10.0 * np.log10(np.maximum(backward_cum / total, 1e-20))
    return edc


def plot_rir_statistics(
    rir: np.ndarray,
    output_path: Optional[str] = None,
) -> None:
    """Plot a 2-panel figure: RIR waveform (top) and energy decay (bottom).

    The energy decay uses Schroeder backward integration.  A −60 dB horizontal
    line and a vertical RT60 marker are drawn automatically.

    Args:
        rir:         1-D float array — the room impulse response h[n].
        output_path: PNG save path.  If None a temporary file is used.
    """
    h = np.asarray(rir, dtype=np.float64).ravel()
    n_samples = len(h)
    t = np.arange(n_samples)

    fig, axes = plt.subplots(2, 1, figsize=(9, 6))
    fig.suptitle("RIR Statistics", fontsize=13, fontweight="bold")

    # ---- Panel 1: waveform ----
    ax0 = axes[0]
    ax0.plot(t, h, color="steelblue", linewidth=0.6)
    ax0.set_xlabel("Sample index n")
    ax0.set_ylabel("Amplitude")
    ax0.set_title("Room Impulse Response h[n]")
    ax0.set_xlim(0, n_samples - 1)
    ax0.grid(True, linestyle="--", alpha=0.4)

    # ---- Panel 2: Schroeder energy decay ----
    ax1 = axes[1]
    edc = _schroeder_decay(h)
    ax1.plot(t, edc, color="darkorange", linewidth=1.0, label="EDC (Schroeder)")

    # −60 dB horizontal line
    ax1.axhline(-60, color="red", linestyle="--", linewidth=1.0, label="-60 dB")

    # RT60 marker: first index where EDC ≤ −60 dB
    below = np.where(edc <= -60.0)[0]
    if len(below) > 0:
        rt60_idx = int(below[0])
        ax1.axvline(rt60_idx, color="green", linestyle=":", linewidth=1.2,
                    label=f"RT60 @ n={rt60_idx}")

    ax1.set_xlabel("Sample index n")
    ax1.set_ylabel("Energy decay (dB)")
    ax1.set_title("Energy Decay Curve (Schroeder integration)")
    ax1.set_xlim(0, n_samples - 1)
    ax1.set_ylim(bottom=max(np.nanmin(edc[np.isfinite(edc)]) - 5, -80) if np.any(np.isfinite(edc)) else -80,
                 top=2)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, linestyle="--", alpha=0.4)

    fig.tight_layout()
    _save_or_show(fig, output_path)


# ---------------------------------------------------------------------------
# UF-W154-03: Multi-channel waveform
# ---------------------------------------------------------------------------


def plot_waveform_channels(
    signal: np.ndarray,
    channel_ids: List[Union[int, str]],
    fs: int,
    output_path: Optional[str] = None,
) -> None:
    """Plot one subplot per channel of a multi-channel audio signal.

    At most 8 channels are shown; a warning is emitted for larger arrays.

    Args:
        signal:      2-D float array, shape (n_channels, n_samples) *or*
                     1-D float array for a single channel.
        channel_ids: Labels for each channel (length must match n_channels).
        fs:          Sample rate in Hz (used to compute time axis in seconds).
        output_path: PNG save path.  If None a temporary file is used.
    """
    sig = np.atleast_2d(np.asarray(signal, dtype=np.float64))
    # Accept (n_samples, n_channels) by transposing if channels dimension is second
    if sig.ndim == 2 and sig.shape[0] > sig.shape[1] and sig.shape[1] <= _MAX_CHANNELS_SHOWN:
        sig = sig.T

    n_channels, n_samples = sig.shape
    t = np.arange(n_samples) / float(fs)

    if n_channels > _MAX_CHANNELS_SHOWN:
        warnings.warn(
            f"Signal has {n_channels} channels; only the first "
            f"{_MAX_CHANNELS_SHOWN} will be plotted.",
            UserWarning,
            stacklevel=2,
        )
        sig = sig[:_MAX_CHANNELS_SHOWN]
        channel_ids = list(channel_ids)[:_MAX_CHANNELS_SHOWN]
        n_channels = _MAX_CHANNELS_SHOWN

    fig, axes = plt.subplots(n_channels, 1, figsize=(10, max(2 * n_channels, 3)),
                             sharex=True, squeeze=False)
    fig.suptitle("Multi-channel Waveform", fontsize=13, fontweight="bold")

    for i in range(n_channels):
        ax = axes[i][0]
        label = channel_ids[i] if i < len(channel_ids) else f"ch{i}"
        ax.plot(t, sig[i], color="steelblue", linewidth=0.5)
        ax.set_ylabel(f"Ch {label}", fontsize=8)
        ax.set_xlim(0, t[-1] if len(t) > 0 else 1.0)
        ax.grid(True, linestyle="--", alpha=0.3)

    axes[-1][0].set_xlabel("Time (s)")
    fig.tight_layout()
    _save_or_show(fig, output_path)


# ---------------------------------------------------------------------------
# UF-W154-04: RT60 octave-band comparison
# ---------------------------------------------------------------------------


def plot_rt60_comparison(
    rt60_per_band: Sequence[float],
    band_centers: Optional[Sequence[float]] = None,
    sabine_rt60: Optional[float] = None,
    output_path: Optional[str] = None,
) -> None:
    """Bar chart comparing RT60 values across octave bands.

    Args:
        rt60_per_band: Sequence of RT60 values (seconds) per octave band.
                       Length should be ≤ 6 (one per standard octave band).
        band_centers:  Optional explicit band centre frequencies (Hz).
                       Defaults to [125, 250, 500, 1000, 2000, 4000].
        sabine_rt60:   Optional Sabine estimate (seconds); plotted as a
                       horizontal dashed line if provided.
        output_path:   PNG save path.  If None a temporary file is used.
    """
    rt60_vals = list(rt60_per_band)
    n_bands = len(rt60_vals)

    if band_centers is not None:
        labels = [f"{int(f)} Hz" if f < 1000 else f"{int(f/1000)} kHz"
                  for f in band_centers[:n_bands]]
    else:
        labels = _DEFAULT_BAND_LABELS[:n_bands]

    x = np.arange(n_bands)
    bar_width = 0.55

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(x, rt60_vals, width=bar_width, color="steelblue",
                  edgecolor="navy", alpha=0.8, label="Measured RT60")

    # Value labels on top of each bar
    for bar in bars:
        h = bar.get_height()
        ax.text(
            bar.get_x() + bar.get_width() / 2.0,
            h + 0.01,
            f"{h:.2f} s",
            ha="center", va="bottom", fontsize=8,
        )

    # Sabine estimate horizontal line
    if sabine_rt60 is not None:
        ax.axhline(
            sabine_rt60,
            color="red",
            linestyle="--",
            linewidth=1.5,
            label=f"Sabine RT60 = {sabine_rt60:.2f} s",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Octave Band")
    ax.set_ylabel("RT60 (s)")
    ax.set_title("RT60 per Octave Band")
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, axis="y", linestyle="--", alpha=0.4)

    fig.tight_layout()
    _save_or_show(fig, output_path)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import os

    print("=== w154_visualization smoke test ===")

    with tempfile.TemporaryDirectory() as tmpdir:

        # --- Room layout ---
        room_bbox = {"L": 6.0, "W": 4.0, "H": 3.0}
        sources = [{"x": 2.0, "z": 2.0}, {"x": 3.5, "z": 1.5}]
        receivers = [{"x": 4.5, "z": 2.5}]
        obstacles = [{"x": 3.0, "z": 2.0, "w": 0.5, "d": 0.3}]
        layout_path = os.path.join(tmpdir, "room_layout.png")
        plot_room_layout(room_bbox, sources, receivers, obstacles, layout_path)
        assert Path(layout_path).exists(), "room_layout.png not created"
        print(f"  room_layout → {layout_path}: OK")

        # --- RIR statistics ---
        rng = np.random.default_rng(0)
        t_ax = np.linspace(0, 1.0, 8000)
        rir = np.exp(-6.9 * t_ax) * rng.standard_normal(8000)
        rir_path = os.path.join(tmpdir, "rir_stats.png")
        plot_rir_statistics(rir, rir_path)
        assert Path(rir_path).exists(), "rir_stats.png not created"
        print(f"  rir_statistics → {rir_path}: OK")

        # --- Waveform channels ---
        signal_4ch = rng.standard_normal((4, 16000)).astype(np.float32)
        wf_path = os.path.join(tmpdir, "waveform_4ch.png")
        plot_waveform_channels(signal_4ch, [0, 1, 2, 3], fs=16000,
                               output_path=wf_path)
        assert Path(wf_path).exists(), "waveform_4ch.png not created"
        print(f"  waveform_channels → {wf_path}: OK")

        # --- RT60 comparison ---
        rt60_bands = [0.55, 0.52, 0.48, 0.43, 0.38, 0.35]
        rt60_path = os.path.join(tmpdir, "rt60_comparison.png")
        plot_rt60_comparison(rt60_bands, sabine_rt60=0.50, output_path=rt60_path)
        assert Path(rt60_path).exists(), "rt60_comparison.png not created"
        print(f"  rt60_comparison → {rt60_path}: OK")

    print("  PASS")
