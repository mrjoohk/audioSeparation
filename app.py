"""
W100000 Spatial Audio Generator — Gradio Web UI
================================================
Launch:
    python app.py
Then open http://localhost:7860 in your browser.

Dependencies (beyond simulator core):
    pip install gradio>=4.0 plotly>=5.0
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup — add src/ so simulator package is importable
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT / "src"))

import gradio as gr
import numpy as np
import plotly.graph_objects as go

from simulator.if_modules.orchestration import simulate_scene
from simulator.types import SceneConfig
from simulator.uf.w151_config import SceneConfigValidator, ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_SAMPLE_RATES = [8000, 16000, 22050, 44100, 48000]
MATERIAL_PRESETS = ["concrete", "brick", "carpet", "glass", "wood", "acoustic_tile", "default"]
MAX_SOURCES = 3
MAX_RECEIVERS = 4


# ---------------------------------------------------------------------------
# 3-D room visualisation (Plotly)
# ---------------------------------------------------------------------------

def _room_edges(L: float, W: float, H: float) -> go.Scatter3d:
    """Return a Scatter3d trace drawing the 12 edges of the shoebox room."""
    x0, y0, z0 = 0.0, 0.0, 0.0
    corners = [
        # bottom face
        (x0, y0, z0), (L, y0, z0), (L, y0, z0), (L, W, z0),
        (L, W, z0), (x0, W, z0), (x0, W, z0), (x0, y0, z0),
        # top face
        (x0, y0, H), (L, y0, H), (L, y0, H), (L, W, H),
        (L, W, H), (x0, W, H), (x0, W, H), (x0, y0, H),
        # verticals
        (x0, y0, z0), (x0, y0, H),
        (L, y0, z0), (L, y0, H),
        (L, W, z0), (L, W, H),
        (x0, W, z0), (x0, W, H),
    ]
    xs, ys, zs = [], [], []
    for i in range(0, len(corners), 2):
        a, b = corners[i], corners[i + 1]
        xs += [a[0], b[0], None]
        ys += [a[1], b[1], None]
        zs += [a[2], b[2], None]
    return go.Scatter3d(
        x=xs, y=ys, z=zs,
        mode="lines",
        line=dict(color="steelblue", width=2),
        name="Room",
        hoverinfo="skip",
    )


def make_room_plot(
    L: float, W: float, H: float,
    sources: List[Tuple[float, float, float]],
    receivers: List[Tuple[float, float, float]],
) -> go.Figure:
    """Build interactive 3-D room plot with source/receiver markers."""
    fig = go.Figure()
    fig.add_trace(_room_edges(L, W, H))

    # Sources (red spheres)
    if sources:
        sx, sy, sz = zip(*sources)
        labels = [f"S{i}" for i in range(len(sources))]
        fig.add_trace(go.Scatter3d(
            x=list(sx), y=list(sy), z=list(sz),
            mode="markers+text",
            marker=dict(size=8, color="crimson", symbol="circle"),
            text=labels, textposition="top center",
            name="Sources",
            customdata=list(range(len(sources))),
        ))

    # Receivers (blue diamonds)
    if receivers:
        rx, ry, rz = zip(*receivers)
        labels = [f"R{i}" for i in range(len(receivers))]
        fig.add_trace(go.Scatter3d(
            x=list(rx), y=list(ry), z=list(rz),
            mode="markers+text",
            marker=dict(size=8, color="royalblue", symbol="diamond"),
            text=labels, textposition="top center",
            name="Receivers",
            customdata=list(range(len(receivers))),
        ))

    # Lines source → receivers
    for s in sources:
        for r in receivers:
            fig.add_trace(go.Scatter3d(
                x=[s[0], r[0]], y=[s[1], r[1]], z=[s[2], r[2]],
                mode="lines",
                line=dict(color="gray", width=1, dash="dot"),
                showlegend=False,
                hoverinfo="skip",
            ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X (m)", range=[0, L]),
            yaxis=dict(title="Y (m)", range=[0, W]),
            zaxis=dict(title="Z (m)", range=[0, H]),
            aspectmode="manual",
            aspectratio=dict(x=L, y=W, z=H),
        ),
        margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(x=0, y=1),
        height=420,
        uirevision="room",  # keep camera angle on update
    )
    return fig


# ---------------------------------------------------------------------------
# Config builder helper
# ---------------------------------------------------------------------------

def _build_config_dict(
    scene_id: str,
    seed: int,
    room_L: float, room_W: float, room_H: float,
    material: str,
    ism_order: int,
    sample_rate: int,
    n_sources: int,
    s0x: float, s0y: float, s0z: float,
    s1x: float, s1y: float, s1z: float,
    s2x: float, s2y: float, s2z: float,
    n_receivers: int,
    r0x: float, r0y: float, r0z: float,
    r1x: float, r1y: float, r1z: float,
    r2x: float, r2y: float, r2z: float,
    r3x: float, r3y: float, r3z: float,
    output_dir: str = "output",
) -> dict:
    source_positions = [
        [s0x, s0y, s0z],
        [s1x, s1y, s1z],
        [s2x, s2y, s2z],
    ]
    receiver_positions = [
        [r0x, r0y, r0z],
        [r1x, r1y, r1z],
        [r2x, r2y, r2z],
        [r3x, r3y, r3z],
    ]
    sources = [
        {"source_id": f"s{i}", "position": source_positions[i]}
        for i in range(int(n_sources))
    ]
    receivers = [
        {"receiver_id": f"r{i}", "position": receiver_positions[i]}
        for i in range(int(n_receivers))
    ]
    return {
        "scene_id": scene_id,
        "seed": int(seed),
        "schema_version": "1.0.0",
        "room": {"type": "shoebox", "dimensions": {"L": room_L, "W": room_W, "H": room_H}},
        "materials": {"default": material},
        "sources": sources,
        "receivers": receivers,
        "sample_rate": int(sample_rate),
        "ism_order": int(ism_order),
        "output_dir": output_dir,
    }


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

def run_single_scene(
    scene_id, seed,
    room_L, room_W, room_H, material,
    ism_order, sample_rate,
    n_sources,
    s0x, s0y, s0z, s1x, s1y, s1z, s2x, s2y, s2z,
    n_receivers,
    r0x, r0y, r0z, r1x, r1y, r1z, r2x, r2y, r2z, r3x, r3y, r3z,
):
    """Called by the Generate button — returns audio paths + summary + plot."""
    tmp_dir = tempfile.mkdtemp(prefix="w100000_")
    cfg_dict = _build_config_dict(
        scene_id=scene_id or "scene_001",
        seed=seed, room_L=room_L, room_W=room_W, room_H=room_H,
        material=material, ism_order=ism_order, sample_rate=sample_rate,
        n_sources=n_sources,
        s0x=s0x, s0y=s0y, s0z=s0z,
        s1x=s1x, s1y=s1y, s1z=s1z,
        s2x=s2x, s2y=s2y, s2z=s2z,
        n_receivers=n_receivers,
        r0x=r0x, r0y=r0y, r0z=r0z,
        r1x=r1x, r1y=r1y, r1z=r1z,
        r2x=r2x, r2y=r2y, r2z=r2z,
        r3x=r3x, r3y=r3y, r3z=r3z,
        output_dir=tmp_dir,
    )
    try:
        config = SceneConfigValidator().validate(cfg_dict)
        result = simulate_scene(config)
    except ValidationError as e:
        return None, None, None, None, f"Validation error: {e}", None
    except Exception as e:
        return None, None, None, None, f"Simulation error: {e}", None

    # Collect WAV paths
    manifest_path = result.get("manifest_path", "")
    wav_paths: List[str] = []
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        wav_paths = [p for p in manifest.get("audio_files", []) if os.path.exists(p)]

    summary = result.get("acoustic_summary")
    summary_rows = []
    if summary:
        summary_rows = [
            ["RT60 (s)", f"{summary.rt60_measured_s:.3f}"],
            ["DRR (dB)", f"{summary.drr_db:.1f}"],
            ["SNR (dB)", f"{summary.snr_db:.1f}"],
            ["DOA Az (°)", f"{summary.doa_az_deg:.1f}"],
            ["DOA El (°)", f"{summary.doa_el_deg:.1f}"],
            ["Elapsed (s)", f"{result.get('elapsed_s', 0):.2f}"],
        ]

    # Return up to 4 audio files
    audio_out = [wav_paths[i] if i < len(wav_paths) else None for i in range(4)]
    status_msg = f"✅ Done — {len(wav_paths)} audio file(s) written to {tmp_dir}"
    return audio_out[0], audio_out[1], audio_out[2], audio_out[3], status_msg, summary_rows


# ---------------------------------------------------------------------------
# Plot update (live 3-D preview)
# ---------------------------------------------------------------------------

def update_plot(
    room_L, room_W, room_H,
    n_sources,
    s0x, s0y, s0z, s1x, s1y, s1z, s2x, s2y, s2z,
    n_receivers,
    r0x, r0y, r0z, r1x, r1y, r1z, r2x, r2y, r2z, r3x, r3y, r3z,
):
    sources_all = [(s0x, s0y, s0z), (s1x, s1y, s1z), (s2x, s2y, s2z)]
    receivers_all = [(r0x, r0y, r0z), (r1x, r1y, r1z), (r2x, r2y, r2z), (r3x, r3y, r3z)]
    sources = sources_all[:int(n_sources)]
    receivers = receivers_all[:int(n_receivers)]
    return make_room_plot(room_L, room_W, room_H, sources, receivers)


# ---------------------------------------------------------------------------
# Config I/O
# ---------------------------------------------------------------------------

def export_config(
    scene_id, seed,
    room_L, room_W, room_H, material,
    ism_order, sample_rate,
    n_sources,
    s0x, s0y, s0z, s1x, s1y, s1z, s2x, s2y, s2z,
    n_receivers,
    r0x, r0y, r0z, r1x, r1y, r1z, r2x, r2y, r2z, r3x, r3y, r3z,
):
    cfg = _build_config_dict(
        scene_id=scene_id or "scene_001",
        seed=seed, room_L=room_L, room_W=room_W, room_H=room_H,
        material=material, ism_order=ism_order, sample_rate=sample_rate,
        n_sources=n_sources,
        s0x=s0x, s0y=s0y, s0z=s0z,
        s1x=s1x, s1y=s1y, s1z=s1z,
        s2x=s2x, s2y=s2y, s2z=s2z,
        n_receivers=n_receivers,
        r0x=r0x, r0y=r0y, r0z=r0z,
        r1x=r1x, r1y=r1y, r1z=r1z,
        r2x=r2x, r2y=r2y, r2z=r2z,
        r3x=r3x, r3y=r3y, r3z=r3z,
    )
    text = json.dumps(cfg, indent=2)
    # Write to temp file for download
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False,
        prefix="scene_config_", encoding="utf-8"
    )
    tmp.write(text)
    tmp.close()
    return tmp.name, text


def import_config(file_obj):
    """Load JSON config file → return values for all fields."""
    if file_obj is None:
        return [gr.update()] * 30 + ["No file uploaded."]
    try:
        with open(file_obj.name, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        return [gr.update()] * 30 + [f"Error reading file: {e}"]

    room = cfg.get("room", {}).get("dimensions", {})
    mats = cfg.get("materials", {})
    sources = cfg.get("sources", [])
    receivers = cfg.get("receivers", [])

    def _pos(lst, idx, axis):
        if idx < len(lst):
            pos = lst[idx].get("position", [1.0, 1.0, 1.0])
            return float(pos[axis]) if axis < len(pos) else 1.0
        return 1.0

    mat_val = list(mats.values())[0] if mats else "concrete"
    if mat_val not in MATERIAL_PRESETS:
        mat_val = "concrete"

    updates = [
        gr.update(value=cfg.get("scene_id", "scene_001")),
        gr.update(value=int(cfg.get("seed", 42))),
        gr.update(value=float(room.get("L", 5.0))),
        gr.update(value=float(room.get("W", 4.0))),
        gr.update(value=float(room.get("H", 3.0))),
        gr.update(value=mat_val),
        gr.update(value=int(cfg.get("ism_order", 3))),
        gr.update(value=int(cfg.get("sample_rate", 16000))),
        gr.update(value=min(len(sources), MAX_SOURCES)),
        gr.update(value=_pos(sources, 0, 0)), gr.update(value=_pos(sources, 0, 1)), gr.update(value=_pos(sources, 0, 2)),
        gr.update(value=_pos(sources, 1, 0)), gr.update(value=_pos(sources, 1, 1)), gr.update(value=_pos(sources, 1, 2)),
        gr.update(value=_pos(sources, 2, 0)), gr.update(value=_pos(sources, 2, 1)), gr.update(value=_pos(sources, 2, 2)),
        gr.update(value=min(len(receivers), MAX_RECEIVERS)),
        gr.update(value=_pos(receivers, 0, 0)), gr.update(value=_pos(receivers, 0, 1)), gr.update(value=_pos(receivers, 0, 2)),
        gr.update(value=_pos(receivers, 1, 0)), gr.update(value=_pos(receivers, 1, 1)), gr.update(value=_pos(receivers, 1, 2)),
        gr.update(value=_pos(receivers, 2, 0)), gr.update(value=_pos(receivers, 2, 1)), gr.update(value=_pos(receivers, 2, 2)),
        gr.update(value=_pos(receivers, 3, 0)), gr.update(value=_pos(receivers, 3, 1)), gr.update(value=_pos(receivers, 3, 2)),
        f"✅ Config loaded: {len(sources)} source(s), {len(receivers)} receiver(s)",
    ]
    return updates


# ---------------------------------------------------------------------------
# Batch generation
# ---------------------------------------------------------------------------

def run_batch_generation(
    n_scenes: int,
    seed_min: int, seed_max: int,
    L_min: float, L_max: float,
    W_min: float, W_max: float,
    H_min: float, H_max: float,
    ism_order: int,
    sample_rate: int,
    output_dir: str,
    progress=gr.Progress(track_tqdm=True),
):
    """Generate multiple randomised scenes, yielding progress rows."""
    rng = np.random.default_rng(seed_min)
    rows = []
    os.makedirs(output_dir, exist_ok=True)

    for i in progress.tqdm(range(int(n_scenes)), desc="Generating scenes"):
        seed = int(rng.integers(seed_min, max(seed_max, seed_min + 1)))
        L = float(rng.uniform(L_min, max(L_max, L_min + 0.1)))
        W = float(rng.uniform(W_min, max(W_max, W_min + 0.1)))
        H = float(rng.uniform(H_min, max(H_max, H_min + 0.1)))

        # Random source/receiver inside room
        src_pos = [float(rng.uniform(0.5, L - 0.5)),
                   float(rng.uniform(0.5, H - 0.5)),
                   float(rng.uniform(0.5, W - 0.5))]
        rec_pos = [float(rng.uniform(0.5, L - 0.5)),
                   float(rng.uniform(0.5, H - 0.5)),
                   float(rng.uniform(0.5, W - 0.5))]

        cfg_dict = {
            "scene_id": f"batch_{i:05d}",
            "seed": seed,
            "schema_version": "1.0.0",
            "room": {"type": "shoebox", "dimensions": {"L": L, "W": W, "H": H}},
            "materials": {"default": "concrete"},
            "sources": [{"source_id": "s0", "position": src_pos}],
            "receivers": [{"receiver_id": "r0", "position": rec_pos}],
            "sample_rate": int(sample_rate),
            "ism_order": int(ism_order),
            "output_dir": output_dir,
        }

        t0 = time.perf_counter()
        try:
            config = SceneConfigValidator().validate(cfg_dict)
            result = simulate_scene(config)
            elapsed = time.perf_counter() - t0
            summary = result.get("acoustic_summary")
            rt60 = f"{summary.rt60_measured_s:.3f}" if summary else "—"
            rows.append([f"batch_{i:05d}", "✅ done", f"{elapsed:.2f}s", rt60])
        except Exception as e:
            elapsed = time.perf_counter() - t0
            rows.append([f"batch_{i:05d}", f"❌ {str(e)[:40]}", f"{elapsed:.2f}s", "—"])

        yield rows, f"Progress: {i+1}/{int(n_scenes)}"

    yield rows, f"✅ Batch complete — {int(n_scenes)} scene(s) written to {output_dir}"


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

_POSITION_INPUTS_HELP = (
    "**Click on the 3D plot** to place the active source/receiver at that XZ position "
    "(Y stays at the current slider value). Use sliders to fine-tune."
)

with gr.Blocks(title="W100000 Spatial Audio Generator") as demo:
    gr.Markdown("# 🎵 W100000 Spatial Audio Generator")
    gr.Markdown(
        "Generate room acoustic datasets for speech separation research. "
        "Configure a scene interactively, run a single simulation or batch-generate thousands of scenes."
    )

    # ---- shared state -------------------------------------------------------
    active_target = gr.State("source_0")  # which point is active for click-to-place

    with gr.Tabs():
        # =====================================================================
        # TAB 1 — Scene Editor
        # =====================================================================
        with gr.Tab("🏠 Scene Editor"):
            with gr.Row():
                # ---- Left panel: parameters ---------------------------------
                with gr.Column(scale=1):
                    gr.Markdown("### Scene Settings")
                    scene_id_in = gr.Textbox(label="Scene ID", value="scene_001")
                    seed_in = gr.Number(label="Random Seed", value=42, precision=0)

                    gr.Markdown("### Room Dimensions")
                    with gr.Row():
                        room_L = gr.Slider(1.0, 20.0, value=5.0, step=0.1, label="Length L (m)")
                        room_W = gr.Slider(1.0, 20.0, value=4.0, step=0.1, label="Width W (m)")
                        room_H = gr.Slider(1.5, 10.0, value=3.0, step=0.1, label="Height H (m)")

                    with gr.Row():
                        material_in = gr.Dropdown(MATERIAL_PRESETS, value="concrete", label="Wall Material")
                        ism_order_in = gr.Slider(1, 10, value=3, step=1, label="ISM Order")
                        sample_rate_in = gr.Dropdown(
                            [str(r) for r in VALID_SAMPLE_RATES], value="16000", label="Sample Rate (Hz)"
                        )

                    gr.Markdown("### Sources (red ●)")
                    n_sources_in = gr.Slider(1, MAX_SOURCES, value=1, step=1, label="Number of Sources")
                    with gr.Group():
                        with gr.Row():
                            s0x = gr.Number(label="S0 X", value=1.0, precision=2)
                            s0y = gr.Number(label="S0 Y", value=1.5, precision=2)
                            s0z = gr.Number(label="S0 Z", value=1.0, precision=2)
                        with gr.Row():
                            s1x = gr.Number(label="S1 X", value=2.5, precision=2)
                            s1y = gr.Number(label="S1 Y", value=1.5, precision=2)
                            s1z = gr.Number(label="S1 Z", value=2.0, precision=2)
                        with gr.Row():
                            s2x = gr.Number(label="S2 X", value=4.0, precision=2)
                            s2y = gr.Number(label="S2 Y", value=1.5, precision=2)
                            s2z = gr.Number(label="S2 Z", value=1.0, precision=2)

                    gr.Markdown("### Receivers (blue ◆)")
                    n_receivers_in = gr.Slider(1, MAX_RECEIVERS, value=1, step=1, label="Number of Receivers")
                    with gr.Group():
                        with gr.Row():
                            r0x = gr.Number(label="R0 X", value=3.0, precision=2)
                            r0y = gr.Number(label="R0 Y", value=1.5, precision=2)
                            r0z = gr.Number(label="R0 Z", value=3.0, precision=2)
                        with gr.Row():
                            r1x = gr.Number(label="R1 X", value=3.5, precision=2)
                            r1y = gr.Number(label="R1 Y", value=1.5, precision=2)
                            r1z = gr.Number(label="R1 Z", value=3.0, precision=2)
                        with gr.Row():
                            r2x = gr.Number(label="R2 X", value=4.0, precision=2)
                            r2y = gr.Number(label="R2 Y", value=1.5, precision=2)
                            r2z = gr.Number(label="R2 Z", value=3.0, precision=2)
                        with gr.Row():
                            r3x = gr.Number(label="R3 X", value=4.5, precision=2)
                            r3y = gr.Number(label="R3 Y", value=1.5, precision=2)
                            r3z = gr.Number(label="R3 Z", value=3.0, precision=2)

                    run_btn = gr.Button("▶ Generate Scene", variant="primary")

                # ---- Right panel: 3-D plot + results ------------------------
                with gr.Column(scale=1):
                    gr.Markdown("### Interactive 3D Room Preview")
                    gr.Markdown(
                        "Rotate: drag | Zoom: scroll | Click a point to see its position. "
                        "Use number inputs on the left to set exact coordinates."
                    )
                    room_plot = gr.Plot(label="Room Layout")

                    gr.Markdown("### Simulation Results")
                    sim_status = gr.Textbox(label="Status", interactive=False)
                    summary_table = gr.Dataframe(
                        headers=["Metric", "Value"],
                        label="Acoustic Summary",
                        interactive=False,
                    )
                    gr.Markdown("#### Output Audio")
                    with gr.Row():
                        audio_r0 = gr.Audio(label="Receiver 0", type="filepath")
                        audio_r1 = gr.Audio(label="Receiver 1", type="filepath")
                    with gr.Row():
                        audio_r2 = gr.Audio(label="Receiver 2", type="filepath")
                        audio_r3 = gr.Audio(label="Receiver 3", type="filepath")

            # ---- Plot inputs list (all triggers for live update) ------------
            _plot_inputs = [
                room_L, room_W, room_H,
                n_sources_in,
                s0x, s0y, s0z, s1x, s1y, s1z, s2x, s2y, s2z,
                n_receivers_in,
                r0x, r0y, r0z, r1x, r1y, r1z, r2x, r2y, r2z, r3x, r3y, r3z,
            ]
            for inp in _plot_inputs:
                inp.change(fn=update_plot, inputs=_plot_inputs, outputs=room_plot)

            # ---- Run simulation --------------------------------------------
            _sim_inputs = [
                scene_id_in, seed_in,
                room_L, room_W, room_H, material_in, ism_order_in, sample_rate_in,
                n_sources_in,
                s0x, s0y, s0z, s1x, s1y, s1z, s2x, s2y, s2z,
                n_receivers_in,
                r0x, r0y, r0z, r1x, r1y, r1z, r2x, r2y, r2z, r3x, r3y, r3z,
            ]
            run_btn.click(
                fn=run_single_scene,
                inputs=_sim_inputs,
                outputs=[audio_r0, audio_r1, audio_r2, audio_r3, sim_status, summary_table],
            )

            # ---- Initial plot render on load --------------------------------
            demo.load(fn=update_plot, inputs=_plot_inputs, outputs=room_plot)

        # =====================================================================
        # TAB 2 — Batch Generator
        # =====================================================================
        with gr.Tab("⚙️ Batch Generator"):
            gr.Markdown("### Batch Scene Generation")
            gr.Markdown(
                "Generates multiple randomised scenes in parallel. "
                "Room dimensions and positions are uniformly sampled within specified ranges."
            )
            with gr.Row():
                with gr.Column():
                    batch_n_scenes = gr.Slider(1, 1000, value=10, step=1, label="Number of Scenes")
                    with gr.Row():
                        batch_seed_min = gr.Number(label="Seed Min", value=0, precision=0)
                        batch_seed_max = gr.Number(label="Seed Max", value=9999, precision=0)
                    gr.Markdown("**Room dimension ranges (m):**")
                    with gr.Row():
                        batch_L_min = gr.Number(label="L min", value=3.0, precision=1)
                        batch_L_max = gr.Number(label="L max", value=10.0, precision=1)
                    with gr.Row():
                        batch_W_min = gr.Number(label="W min", value=3.0, precision=1)
                        batch_W_max = gr.Number(label="W max", value=8.0, precision=1)
                    with gr.Row():
                        batch_H_min = gr.Number(label="H min", value=2.5, precision=1)
                        batch_H_max = gr.Number(label="H max", value=4.0, precision=1)
                    with gr.Row():
                        batch_ism = gr.Slider(1, 6, value=3, step=1, label="ISM Order")
                        batch_sr = gr.Dropdown(
                            [str(r) for r in VALID_SAMPLE_RATES], value="16000", label="Sample Rate"
                        )
                    batch_output_dir = gr.Textbox(label="Output Directory", value="output/batch")
                    batch_btn = gr.Button("▶ Start Batch", variant="primary")

                with gr.Column():
                    batch_status = gr.Textbox(label="Status", interactive=False)
                    batch_table = gr.Dataframe(
                        headers=["Scene ID", "Status", "Elapsed", "RT60 (s)"],
                        label="Progress",
                        interactive=False,
                    )

            batch_btn.click(
                fn=run_batch_generation,
                inputs=[
                    batch_n_scenes,
                    batch_seed_min, batch_seed_max,
                    batch_L_min, batch_L_max,
                    batch_W_min, batch_W_max,
                    batch_H_min, batch_H_max,
                    batch_ism, batch_sr,
                    batch_output_dir,
                ],
                outputs=[batch_table, batch_status],
            )

        # =====================================================================
        # TAB 3 — Results Viewer
        # =====================================================================
        with gr.Tab("📊 Results Viewer"):
            gr.Markdown("### Load & Inspect Scene Manifest")
            gr.Markdown(
                "Upload a `scene_manifest.json` file from a previously generated scene "
                "to view audio, acoustic metrics, and plots."
            )
            manifest_upload = gr.File(label="Upload scene_manifest.json", file_types=[".json"])
            load_manifest_btn = gr.Button("Load Manifest")

            with gr.Row():
                viewer_audio_r0 = gr.Audio(label="Receiver 0", type="filepath")
                viewer_audio_r1 = gr.Audio(label="Receiver 1", type="filepath")
                viewer_audio_r2 = gr.Audio(label="Receiver 2", type="filepath")
                viewer_audio_r3 = gr.Audio(label="Receiver 3", type="filepath")

            viewer_summary = gr.Dataframe(
                headers=["Field", "Value"],
                label="Acoustic Summary",
                interactive=False,
            )
            viewer_manifest_json = gr.Code(label="Manifest JSON", language="json")

            def load_manifest_file(file_obj):
                if file_obj is None:
                    return None, None, None, None, [], ""
                try:
                    with open(file_obj.name, encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception as e:
                    return None, None, None, None, [["Error", str(e)]], ""

                wav_paths = [p for p in manifest.get("audio_files", []) if os.path.exists(p)]
                audio_out = [wav_paths[i] if i < len(wav_paths) else None for i in range(4)]

                ac = manifest.get("acoustic_summary", {})
                summary_rows = [[k, str(v)] for k, v in ac.items()]

                return (
                    audio_out[0], audio_out[1], audio_out[2], audio_out[3],
                    summary_rows,
                    json.dumps(manifest, indent=2),
                )

            load_manifest_btn.click(
                fn=load_manifest_file,
                inputs=[manifest_upload],
                outputs=[
                    viewer_audio_r0, viewer_audio_r1, viewer_audio_r2, viewer_audio_r3,
                    viewer_summary, viewer_manifest_json,
                ],
            )

        # =====================================================================
        # TAB 4 — Config I/O
        # =====================================================================
        with gr.Tab("💾 Config I/O"):
            gr.Markdown("### Save / Load Scene Configuration")
            gr.Markdown(
                "Export the current Scene Editor settings to JSON, or upload an existing "
                "config file to populate the Scene Editor."
            )

            with gr.Row():
                with gr.Column():
                    gr.Markdown("#### Export Current Config")
                    export_btn = gr.Button("⬇ Download Config as JSON", variant="secondary")
                    config_download = gr.File(label="Download", interactive=False)
                    config_preview = gr.Code(label="Config Preview", language="json")

                with gr.Column():
                    gr.Markdown("#### Import Config File")
                    config_upload = gr.File(label="Upload JSON Config", file_types=[".json", ".yaml", ".yml"])
                    import_btn = gr.Button("⬆ Load into Scene Editor", variant="secondary")
                    import_status = gr.Textbox(label="Import Status", interactive=False)

            _export_inputs = [
                scene_id_in, seed_in,
                room_L, room_W, room_H, material_in, ism_order_in, sample_rate_in,
                n_sources_in,
                s0x, s0y, s0z, s1x, s1y, s1z, s2x, s2y, s2z,
                n_receivers_in,
                r0x, r0y, r0z, r1x, r1y, r1z, r2x, r2y, r2z, r3x, r3y, r3z,
            ]
            export_btn.click(
                fn=export_config,
                inputs=_export_inputs,
                outputs=[config_download, config_preview],
            )

            _import_outputs = [
                scene_id_in, seed_in,
                room_L, room_W, room_H, material_in, ism_order_in, sample_rate_in,
                n_sources_in,
                s0x, s0y, s0z, s1x, s1y, s1z, s2x, s2y, s2z,
                n_receivers_in,
                r0x, r0y, r0z, r1x, r1y, r1z, r2x, r2y, r2z, r3x, r3y, r3z,
                import_status,
            ]
            import_btn.click(
                fn=import_config,
                inputs=[config_upload],
                outputs=_import_outputs,
            )


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        theme=gr.themes.Soft(),
    )
