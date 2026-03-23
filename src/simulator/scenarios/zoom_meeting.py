"""
Zoom Meeting Scenario Generator
================================
Generates physically plausible SceneConfig-compatible dicts for a
video-conference (Zoom-style) room simulation.

Room layout (Y-up right-hand coordinate system):
  X = 0 .. L   (room length, front-to-back)
  Y = 0 .. H   (height, vertical)
  Z = 0 .. W   (room width, left-to-right)

  "Camera wall" = X = 0  (TV + conference mic are near here)
  Participants  = seated on both long sides of a central table

Usage
-----
    from simulator.scenarios.zoom_meeting import generate_zoom_scenario, generate_zoom_scenarios, save_scenarios

    # Single scene
    cfg = generate_zoom_scenario(n_participants=4, seed=42)

    # Batch
    cfgs = generate_zoom_scenarios(n_scenarios=20, min_participants=2, max_participants=8, seed_base=0)
    paths = save_scenarios(cfgs, output_dir="output/scenarios")
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Room / Table size lookup tables
# ---------------------------------------------------------------------------

_ROOM_SIZES: Dict[str, Dict[str, float]] = {
    "small":  {"L": 6.0, "W": 4.0, "H": 2.8},   # 2-4 participants
    "medium": {"L": 9.0, "W": 5.0, "H": 3.0},   # 5-8 participants
    "large":  {"L": 12.0, "W": 6.0, "H": 3.5},  # 9-12 participants
}

# Table dimensions [table_L, table_H, table_W] in meters (X-extent, height, Z-extent)
_TABLE_SIZES: List[tuple] = [
    # max_participants, (table_L, table_H, table_W)
    (4,  (2.0, 0.75, 0.90)),
    (8,  (3.0, 0.75, 1.10)),
    (12, (4.2, 0.75, 1.30)),
]

# Seated person mouth height from floor (seat 0.45 m + torso+head 0.73 m)
_MOUTH_HEIGHT_M: float = 1.18

# Distance a seated person's mouth is from the table's long edge (Z direction)
_SEAT_EDGE_OFFSET_M: float = 0.30

# Chair depth behind person's seat position
_CHAIR_BEHIND_M: float = 0.40

# Conference mic height above table surface
_MIC_ABOVE_TABLE_M: float = 0.05

# TV specs (mounted on X=0 wall, facing room)
_TV_DEPTH_M: float = 0.10    # X dimension (wall-normal)
_TV_HEIGHT_M: float = 0.81   # Y dimension (65" 16:9 height)
_TV_WIDTH_M: float = 1.44    # Z dimension (65" 16:9 width)
_TV_CENTER_Y_M: float = 1.50  # TV screen center height


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _room_dims(n: int, override: str = "auto") -> Dict[str, float]:
    if override != "auto":
        return dict(_ROOM_SIZES[override])
    if n <= 4:
        return dict(_ROOM_SIZES["small"])
    if n <= 8:
        return dict(_ROOM_SIZES["medium"])
    return dict(_ROOM_SIZES["large"])


def _table_dims(n: int) -> tuple:
    for max_n, dims in _TABLE_SIZES:
        if n <= max_n:
            return dims
    return _TABLE_SIZES[-1][1]


def _seat_positions(
    n: int,
    cx: float, cz: float,
    table_L: float, table_H: float, table_W: float,
) -> List[Dict[str, Any]]:
    """
    Return list of dicts with keys 'position' [x,y,z] and 'side' ('front'|'back').

    People sit on both long sides (Z-sides) of the table, evenly distributed
    along the table length (X axis).

    Front side: Z = cz - table_W/2 - SEAT_EDGE_OFFSET
    Back  side: Z = cz + table_W/2 + SEAT_EDGE_OFFSET
    """
    n_front = math.ceil(n / 2)
    n_back = n - n_front

    seats = []

    # --- Front row (low Z) ---
    z_front = cz - table_W / 2.0 - _SEAT_EDGE_OFFSET_M
    table_x_start = cx - table_L / 2.0
    for i in range(n_front):
        x = table_x_start + table_L * (i + 1) / (n_front + 1)
        seats.append({"position": [x, _MOUTH_HEIGHT_M, z_front], "side": "front"})

    # --- Back row (high Z) ---
    z_back = cz + table_W / 2.0 + _SEAT_EDGE_OFFSET_M
    for j in range(n_back):
        x = table_x_start + table_L * (j + 1) / (n_back + 1)
        seats.append({"position": [x, _MOUTH_HEIGHT_M, z_back], "side": "back"})

    return seats


def _chair_position(seat_pos: List[float], side: str) -> List[float]:
    """Chair centroid: behind the person (away from table), at seat height."""
    x, y, z = seat_pos
    offset = _CHAIR_BEHIND_M
    chair_z = z - offset if side == "front" else z + offset
    chair_y = 0.45  # seat height
    chair_size_half_y = 0.45
    return [x, chair_y, chair_z]


def _round2(v: float) -> float:
    return round(float(v), 3)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_zoom_scenario(
    n_participants: int,
    seed: int,
    room_size: str = "auto",
    material: str = "concrete",
    has_tv: bool = True,
    tv_as_source: bool = False,
    sample_rate: int = 16000,
    ism_order: int = 3,
    output_dir: str = "output",
    scene_id: Optional[str] = None,
) -> dict:
    """Generate a single Zoom-meeting SceneConfig-compatible dict.

    Parameters
    ----------
    n_participants : int
        Number of meeting participants (2-12).
    seed : int
        Random seed for reproducibility.
    room_size : str
        "auto" (size chosen by n_participants), "small", "medium", or "large".
    material : str
        Default wall material name (see MaterialDB presets).
    has_tv : bool
        If True, add a large TV on the camera wall as a reflective obstacle.
    tv_as_source : bool
        If True AND has_tv is True, add a "tv_speaker" source at the TV position
        (models audio from remote participants playing through the TV).
    sample_rate : int
        Audio sample rate in Hz.
    ism_order : int
        Image Source Method reflection order (1-6 recommended).
    output_dir : str
        Base output directory for simulation results.
    scene_id : str, optional
        Custom scene identifier. Auto-generated as "zoom_{seed:06d}" if None.

    Returns
    -------
    dict
        SceneConfig-compatible dict ready for SceneConfigValidator.validate().
    """
    n_participants = max(2, min(12, int(n_participants)))
    if scene_id is None:
        scene_id = f"zoom_{seed:06d}_n{n_participants}"

    dims = _room_dims(n_participants, room_size)
    L, W, H = dims["L"], dims["W"], dims["H"]

    table_L, table_H, table_W = _table_dims(n_participants)
    cx = L / 2.0   # table center X
    cz = W / 2.0   # table center Z

    # --- Sources: participant mouths ---
    seats = _seat_positions(n_participants, cx, cz, table_L, table_H, table_W)
    sources = []
    for i, seat in enumerate(seats):
        sources.append({
            "source_id": f"person_{i}",
            "position": [_round2(v) for v in seat["position"]],
        })

    # TV speaker as additional source
    tv_center_x = _TV_DEPTH_M / 2.0
    tv_center_z = cz
    if has_tv and tv_as_source:
        sources.append({
            "source_id": "tv_speaker",
            "position": [_round2(tv_center_x + 0.05), _round2(_TV_CENTER_Y_M), _round2(tv_center_z)],
        })

    # --- Receiver: conference mic on table surface, at center ---
    mic_x = cx
    mic_y = table_H + _MIC_ABOVE_TABLE_M
    mic_z = cz
    receivers = [{
        "receiver_id": "conf_mic",
        "position": [_round2(mic_x), _round2(mic_y), _round2(mic_z)],
    }]

    # --- Obstacles ---
    obstacles = []

    # Conference table (centered in room)
    table_cx = cx
    table_cy = table_H / 2.0      # centroid Y (PlacedObject uses centroid)
    table_cz = cz
    obstacles.append({
        "type": "table",
        "size": [table_L, table_H, table_W],
        "position": [_round2(table_cx), _round2(table_cy), _round2(table_cz)],
        "acoustic_role": "reflective",
        "rotation_y": 0.0,
    })

    # Chairs (one per participant)
    chair_sx, chair_sy, chair_sz = 0.50, 0.90, 0.50
    for seat in seats:
        cp = _chair_position(seat["position"], seat["side"])
        obstacles.append({
            "type": "chair",
            "size": [chair_sx, chair_sy, chair_sz],
            "position": [_round2(cp[0]), _round2(cp[1]), _round2(cp[2])],
            "acoustic_role": "absorptive",
            "rotation_y": 0.0,
        })

    # TV on camera wall (X = 0)
    if has_tv:
        tv_cx = _TV_DEPTH_M / 2.0
        tv_cy = _TV_CENTER_Y_M
        tv_cz = cz
        obstacles.append({
            "type": "tv",
            "size": [_TV_DEPTH_M, _TV_HEIGHT_M, _TV_WIDTH_M],
            "position": [_round2(tv_cx), _round2(tv_cy), _round2(tv_cz)],
            "acoustic_role": "reflective",
            "rotation_y": 0.0,
        })

    return {
        "scene_id": scene_id,
        "seed": int(seed),
        "schema_version": "1.0.0",
        "room": {
            "type": "shoebox",
            "dimensions": {"L": L, "W": W, "H": H},
            "obstacles": obstacles,
        },
        "materials": {"default": material},
        "sources": sources,
        "receivers": receivers,
        "sample_rate": int(sample_rate),
        "ism_order": int(ism_order),
        "output_dir": output_dir,
        # Metadata (not used by simulator, preserved in JSON for reference)
        "_zoom_meta": {
            "n_participants": n_participants,
            "has_tv": has_tv,
            "tv_as_source": tv_as_source,
            "room_size_preset": room_size,
            "table_dims": list(_table_dims(n_participants)),
        },
    }


def generate_zoom_scenarios(
    n_scenarios: int,
    min_participants: int = 2,
    max_participants: int = 8,
    seed_base: int = 0,
    output_dir: str = "output",
    **kwargs: Any,
) -> List[dict]:
    """Generate a batch of randomised Zoom meeting scenarios.

    Parameters
    ----------
    n_scenarios : int
        Number of scenarios to generate.
    min_participants : int
        Minimum participant count (inclusive).
    max_participants : int
        Maximum participant count (inclusive).
    seed_base : int
        Base seed; scenario i uses seed = seed_base + i.
    output_dir : str
        Passed through to each scenario's output_dir field.
    **kwargs
        Additional keyword arguments forwarded to generate_zoom_scenario
        (e.g. material, has_tv, tv_as_source, sample_rate, ism_order).

    Returns
    -------
    List[dict]
        List of SceneConfig-compatible dicts.
    """
    rng = np.random.default_rng(seed_base)
    scenarios = []
    for i in range(int(n_scenarios)):
        n = int(rng.integers(min_participants, max_participants + 1))
        seed = seed_base + i
        cfg = generate_zoom_scenario(
            n_participants=n,
            seed=seed,
            output_dir=output_dir,
            **kwargs,
        )
        scenarios.append(cfg)
    return scenarios


def save_scenarios(scenarios: List[dict], output_dir: str) -> List[str]:
    """Save each scenario dict as a JSON file.

    Parameters
    ----------
    scenarios : list of dict
        Scenario dicts (from generate_zoom_scenario / generate_zoom_scenarios).
    output_dir : str
        Directory where JSON files are written.

    Returns
    -------
    List[str]
        Absolute paths of the saved JSON files.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for cfg in scenarios:
        fname = f"{cfg['scene_id']}.json"
        fpath = out / fname
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        paths.append(str(fpath.resolve()))
    return paths


def load_scenario_from_file(path: str) -> dict:
    """Load a scenario JSON file and return the raw dict."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
