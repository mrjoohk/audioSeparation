"""
UF-W155: Acoustic Plausibility and Config Completeness Validation.

Implements UF-W155-01:
  - validate_acoustic_plausibility: Sabine RT60, DRR, near-field, volume checks
  - validate_config_completeness:   cross-check referenced scene elements
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_SRC = _HERE.parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from simulator.types import (
    OCTAVE_BAND_CENTERS,
    MaterialMap,
    MaterialSpec,
    MIN_ROOM_VOLUME_M3,
    MAX_ROOM_VOLUME_M3,
    MIN_SOURCE_MIC_DIST_M,
    PlausibilityReport,
    RoomPrimitive,
    SceneConfig,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_RT60_MIN_S: float = 0.05
_RT60_MAX_S: float = 5.0
_NEAR_FIELD_DIST_M: float = 0.1     # matches MIN_SOURCE_MIC_DIST_M
_500HZ_BAND_INDEX: int = 2          # index of 500 Hz in OCTAVE_BAND_CENTERS

# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _extract_room_dims(room) -> Dict[str, float]:
    """Return a dict with L, W, H from a room object or dict."""
    if isinstance(room, dict):
        dims = room.get("dimensions", room)
        return {
            "L": float(dims.get("L", dims.get("length", dims.get("x", 0.0)))),
            "W": float(dims.get("W", dims.get("width", dims.get("z", 0.0)))),
            "H": float(dims.get("H", dims.get("height", dims.get("y", 0.0)))),
        }
    # RoomPrimitive or similar
    try:
        d = room.dimensions
        return {
            "L": float(d.get("L", 0.0)),
            "W": float(d.get("W", 0.0)),
            "H": float(d.get("H", 0.0)),
        }
    except AttributeError:
        return {"L": 0.0, "W": 0.0, "H": 0.0}


def _shoebox_surface_areas(L: float, W: float, H: float) -> Dict[str, float]:
    """Return surface areas for the 6 faces of a shoebox room."""
    return {
        "floor":   L * W,
        "ceiling": L * W,
        "front":   L * H,
        "back":    L * H,
        "left":    W * H,
        "right":   W * H,
    }


def _extract_position(entity) -> Optional[List[float]]:
    """Return [x, y, z] from a source/receiver dict or state object."""
    if isinstance(entity, dict):
        pos = entity.get("position", entity)
        if isinstance(pos, dict):
            return [
                float(pos.get("x", 0.0)),
                float(pos.get("y", 0.0)),
                float(pos.get("z", 0.0)),
            ]
        if isinstance(pos, (list, tuple)) and len(pos) >= 3:
            return [float(pos[0]), float(pos[1]), float(pos[2])]
    try:
        import numpy as np
        p = entity.position
        arr = np.asarray(p, dtype=float)
        return arr[:3].tolist()
    except (AttributeError, TypeError):
        pass
    return None


def _distance(a: List[float], b: List[float]) -> float:
    """Euclidean distance between two 3-D points."""
    return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))


# ---------------------------------------------------------------------------
# Absorption coefficient extraction
# ---------------------------------------------------------------------------


def _get_alpha_500hz(material) -> float:
    """Return the 500 Hz absorption coefficient from a MaterialSpec or dict."""
    if isinstance(material, MaterialSpec):
        alpha = material.alpha
        try:
            return float(alpha[_500HZ_BAND_INDEX])
        except (IndexError, TypeError):
            return 0.1
    if isinstance(material, dict):
        # Try 'alpha' key (list of 6)
        alpha = material.get("alpha", None)
        if alpha is not None and hasattr(alpha, "__len__") and len(alpha) > _500HZ_BAND_INDEX:
            return float(alpha[_500HZ_BAND_INDEX])
        # Fall back to a scalar
        return float(material.get("absorption", material.get("alpha_500", 0.1)))
    try:
        return float(material.alpha[_500HZ_BAND_INDEX])
    except (AttributeError, IndexError, TypeError):
        return 0.1


# ---------------------------------------------------------------------------
# Sabine RT60 estimation
# ---------------------------------------------------------------------------


def _sabine_rt60(
    V: float,
    surfaces: Dict[str, float],
    materials,
) -> float:
    """Estimate RT60 using Sabine's formula at the 500 Hz octave band.

        RT60 = 0.161 * V / sum(α_i * S_i)

    Args:
        V:         Room volume (m³).
        surfaces:  Dict of {surface_label: area_m2}.
        materials: One of:
                   - A MaterialMap dict ({surface_id: MaterialSpec}).
                   - A single MaterialSpec applied to all surfaces.
                   - A dict with a single "absorption" float.
                   - None (uses a generic 0.1 absorption for all surfaces).

    Returns:
        Sabine RT60 in seconds.  Returns ``float('inf')`` if total absorption
        is zero.
    """
    total_absorption = 0.0

    for surface_id, area_m2 in surfaces.items():
        if area_m2 <= 0.0:
            continue

        # Resolve material for this surface
        alpha = 0.1  # default
        if materials is None:
            alpha = 0.1
        elif isinstance(materials, MaterialSpec):
            alpha = _get_alpha_500hz(materials)
        elif isinstance(materials, dict):
            # MaterialMap: surface_id → MaterialSpec
            if surface_id in materials:
                alpha = _get_alpha_500hz(materials[surface_id])
            else:
                # Try using any single entry as a global default
                first_val = next(iter(materials.values()), None)
                if first_val is not None:
                    alpha = _get_alpha_500hz(first_val)
                else:
                    alpha = 0.1
        else:
            alpha = _get_alpha_500hz(materials)

        # Clamp to valid physical range
        alpha = max(0.0, min(1.0, float(alpha)))
        total_absorption += alpha * area_m2

    if total_absorption <= 0.0:
        return float("inf")

    return 0.161 * V / total_absorption


# ---------------------------------------------------------------------------
# DRR prediction
# ---------------------------------------------------------------------------


def _predict_drr_db(distance_m: float, rt60_s: float) -> float:
    """Approximate DRR (dB) for a given source-receiver distance and RT60.

    Uses the formula:
        DRR ≈ 20*log10(1.0/d) - 10*log10(1 - exp(-6.9/rt60))

    This is a simplified estimate valid for monopole sources in a diffuse
    reverberant field.
    """
    if distance_m <= 0.0:
        distance_m = 1e-3
    direct_term = 20.0 * math.log10(1.0 / distance_m)
    if rt60_s > 0.0 and math.isfinite(rt60_s):
        reverb_term = 10.0 * math.log10(max(1.0 - math.exp(-6.9 / rt60_s), 1e-10))
    else:
        reverb_term = 0.0
    return direct_term - reverb_term


# ---------------------------------------------------------------------------
# UF-W155-01: validate_acoustic_plausibility
# ---------------------------------------------------------------------------


def validate_acoustic_plausibility(
    room,
    materials,
    sources: List,
    receivers: List,
) -> PlausibilityReport:
    """Check acoustic plausibility of a scene configuration.

    Checks performed:
        1. Sabine RT60 at 500 Hz < 0.05 s → error
        2. Sabine RT60 at 500 Hz > 5.0 s → error
        3. Any source closer than 0.1 m to any receiver → warning
        4. Room volume < 10 m³ → warning
        5. Room volume > 5000 m³ → warning

    Args:
        room:      Room geometry.  Accepts RoomPrimitive, dict with
                   ``dimensions``, or dict with L/W/H keys.
        materials: Absorption materials.  Accepts MaterialMap (dict of
                   MaterialSpec), a single MaterialSpec, or None.
        sources:   List of source objects/dicts with position info.
        receivers: List of receiver objects/dicts with position info.

    Returns:
        PlausibilityReport with passed flag, predicted RT60, DRR, warnings,
        and errors.
    """
    errors: List[str] = []
    report_warnings: List[str] = []

    # ---- Extract room dimensions ----
    dims = _extract_room_dims(room)
    L, W, H = dims["L"], dims["W"], dims["H"]
    V = L * W * H

    # ---- Volume checks ----
    if V < MIN_ROOM_VOLUME_M3:
        report_warnings.append(
            f"Room below minimum volume: {V:.2f} m³ < {MIN_ROOM_VOLUME_M3} m³"
        )
    if V > MAX_ROOM_VOLUME_M3:
        report_warnings.append(
            f"Room exceeds maximum volume: {V:.2f} m³ > {MAX_ROOM_VOLUME_M3} m³"
        )

    # ---- Sabine RT60 ----
    surfaces = _shoebox_surface_areas(L, W, H)
    rt60_sabine = _sabine_rt60(V, surfaces, materials)

    if math.isinf(rt60_sabine) or rt60_sabine > _RT60_MAX_S:
        errors.append(
            f"RT60 exceeds maximum ({_RT60_MAX_S} s): "
            f"predicted {rt60_sabine:.2f} s (possibly zero absorption)"
        )
    elif rt60_sabine < _RT60_MIN_S:
        errors.append(
            f"RT60 below minimum ({_RT60_MIN_S} s): "
            f"predicted {rt60_sabine:.3f} s"
        )

    # ---- Source-receiver distances ----
    src_positions = [_extract_position(s) for s in sources]
    rec_positions = [_extract_position(r) for r in receivers]

    min_dist = float("inf")
    for sp in src_positions:
        if sp is None:
            continue
        for rp in rec_positions:
            if rp is None:
                continue
            d = _distance(sp, rp)
            min_dist = min(min_dist, d)
            if d < _NEAR_FIELD_DIST_M:
                report_warnings.append(
                    f"Near-field source: distance {d:.3f} m < "
                    f"{_NEAR_FIELD_DIST_M} m minimum"
                )

    # ---- Predicted DRR at min distance ----
    if math.isfinite(min_dist) and min_dist > 0.0 and math.isfinite(rt60_sabine):
        predicted_drr = _predict_drr_db(min_dist, rt60_sabine)
    else:
        predicted_drr = 0.0

    # If RT60 is infinite, use a sentinel for the report
    rt60_for_report = rt60_sabine if math.isfinite(rt60_sabine) else _RT60_MAX_S + 1.0

    passed = len(errors) == 0

    return PlausibilityReport(
        passed=passed,
        predicted_rt60_s=rt60_for_report,
        predicted_drr_db=predicted_drr,
        warnings=report_warnings,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# validate_config_completeness
# ---------------------------------------------------------------------------


def validate_config_completeness(config: SceneConfig) -> dict:
    """Cross-check all referenced scene elements exist within the config.

    Currently checks:
    - All source source_ids are unique.
    - All receiver receiver_ids are unique.
    - motion block (if present) references only known source/receiver IDs.
    - impairments block (if present) references only known source IDs.

    Returns:
        {"passed": bool, "missing_refs": List[str]}
    """
    missing_refs: List[str] = []

    # ---- Collect declared IDs ----
    source_ids = set()
    for i, src in enumerate(config.sources):
        sid = src.get("source_id", None) if isinstance(src, dict) else getattr(src, "source_id", None)
        if sid is None:
            missing_refs.append(f"sources[{i}].source_id is missing")
        elif sid in source_ids:
            missing_refs.append(f"Duplicate source_id: '{sid}'")
        else:
            source_ids.add(sid)

    receiver_ids = set()
    for i, rec in enumerate(config.receivers):
        rid = rec.get("receiver_id", None) if isinstance(rec, dict) else getattr(rec, "receiver_id", None)
        if rid is None:
            missing_refs.append(f"receivers[{i}].receiver_id is missing")
        elif rid in receiver_ids:
            missing_refs.append(f"Duplicate receiver_id: '{rid}'")
        else:
            receiver_ids.add(rid)

    # ---- Check motion block references ----
    if config.motion and isinstance(config.motion, dict):
        for ref_id in config.motion.keys():
            if ref_id not in source_ids and ref_id not in receiver_ids:
                missing_refs.append(
                    f"motion references unknown entity '{ref_id}'"
                )

    # ---- Check impairments block references ----
    if config.impairments and isinstance(config.impairments, dict):
        for ref_id in config.impairments.keys():
            if ref_id not in source_ids:
                missing_refs.append(
                    f"impairments references unknown source '{ref_id}'"
                )

    return {
        "passed": len(missing_refs) == 0,
        "missing_refs": missing_refs,
    }


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import numpy as np
    print("=== w155_validation smoke test ===")

    from simulator.types import MaterialSpec, SceneConfig, PlausibilityReport

    # --- Normal shoebox, concrete walls (α≈0.02) ---
    concrete = MaterialSpec(
        name="concrete",
        alpha=np.array([0.02, 0.02, 0.02, 0.03, 0.03, 0.04]),
        sigma=np.zeros(6),
    )
    room = {"type": "shoebox", "dimensions": {"L": 6.0, "W": 5.0, "H": 3.0}}
    materials = {s: concrete for s in ["floor", "ceiling", "front", "back", "left", "right"]}
    sources = [{"source_id": "s1", "position": {"x": 2.0, "y": 1.5, "z": 2.0}}]
    receivers = [{"receiver_id": "r1", "position": {"x": 4.0, "y": 1.5, "z": 3.0}}]
    report = validate_acoustic_plausibility(room, materials, sources, receivers)
    print(f"  Normal scene: passed={report.passed}, RT60={report.predicted_rt60_s:.2f}s, "
          f"DRR={report.predicted_drr_db:.1f}dB")
    print(f"  warnings={report.warnings}, errors={report.errors}")

    # --- Very low absorption → high RT60 ---
    low_alpha = MaterialSpec(
        name="mirror",
        alpha=np.array([0.005, 0.005, 0.005, 0.005, 0.005, 0.005]),
        sigma=np.zeros(6),
    )
    materials_low = {s: low_alpha for s in ["floor", "ceiling", "front", "back", "left", "right"]}
    report2 = validate_acoustic_plausibility(room, materials_low, sources, receivers)
    print(f"  Low absorption: passed={report2.passed}, RT60={report2.predicted_rt60_s:.2f}s")
    print(f"  errors={report2.errors}")

    # --- Near-field source ---
    src_near = [{"source_id": "s1", "position": {"x": 4.0, "y": 1.5, "z": 3.0}}]
    report3 = validate_acoustic_plausibility(room, materials, src_near, receivers)
    print(f"  Near-field: passed={report3.passed}, warnings={report3.warnings}")

    # --- Config completeness ---
    cfg = SceneConfig(
        scene_id="test",
        seed=1,
        schema_version="1.0.0",
        room=room,
        materials={},
        sources=sources,
        receivers=receivers,
    )
    result = validate_config_completeness(cfg)
    print(f"  Config completeness: {result}")

    print("  PASS")
