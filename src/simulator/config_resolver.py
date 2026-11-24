"""
Shared scene-config interpreter for the Python API, batch runner and GUI.

Design: design_md/W100000/W1_audit_remediation_design.md §2, §4.5, §4.6 (F-07, F-08, F-09).

The GUI used to rebuild configs from its widgets (dropping obstacles, extra
sources, IDs and device settings) and parsed YAML with a JSON parser.  Every
path now goes through these functions:

* :func:`load_raw_config`       JSON/YAML loader (same as the API)
* :func:`resolve_config`        defaults + normalisation (no I/O)
* :func:`check_profile`         supported-feature gate for ``static_v1``
* :func:`render_fingerprint`    identity of a render job (ignores display ID/output dir)
* :func:`apply_editor_overrides` merge editor widgets into a base config, preserving the rest
* :func:`preflight`             errors/warnings/approximations/workload before running
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from simulator.types import DEFAULT_DURATION_S, DEFAULT_TICK_RATE_HZ, MAX_RIR_DURATION_S
from simulator.uf.w151_config import (
    SCENE_CONFIG_SCHEMA_VERSION,
    SceneConfigValidator,
    ValidationError,
    load_config_from_file,
    position_to_list,
)
from simulator.scene_io import RENDERER_VERSION, canonical_json, sha256_file

RENDER_PROFILE = "static_v1"
RENDER_PROFILES = ("static_v1", "dynamic_v1")
# "full": mixture, references, noise, dry, RIRs.  "training": mixture + references only
# (F-11: store what training needs; noise/dry/RIR are diagnostics).
STORAGE_PROFILES = ("full", "training")
SOURCE_ROLES = ("speech", "noise", "interference")
STATIC_MOTION_TYPES = ("static", "array_mounted")
SUPPORTED_IMPAIRMENTS = ("none", "bandwidth", "codec", "packet_loss")
RECEIVER_DEVICE_DEFAULTS = {
    "noise_floor_dbfs": -60.0,
    "gain_db": 0.0,
    "clip_threshold_dbfs": 0.0,
    "sensitivity_db": 0.0,
    "agc_enabled": False,
    "pattern": "omni",
}
VALIDATED_QUANTITIES = [
    "direct_path_delay",
    "direct_path_attenuation",
    "image_source_delay",
    "broadband_rt60_drr",
]
# Keys that identify *where/how a job is shown*, not what is rendered.
_NON_RENDER_KEYS = ("scene_id", "output_dir")
KNOWN_TOP_LEVEL_KEYS = frozenset({
    "scene_id", "seed", "schema_version", "room", "materials", "sources", "receivers",
    "motion", "impairments", "output_dir", "sample_rate", "ism_order", "speed_of_sound",
    "render", "qc", "reference_receiver", "mix",
})


# ---------------------------------------------------------------------------
# Loading and resolution
# ---------------------------------------------------------------------------

def load_raw_config(path: str) -> dict:
    """Load a JSON or YAML scene config (identical behaviour for API and GUI)."""
    raw = load_config_from_file(path)
    if not isinstance(raw, dict):
        raise ValidationError("Config file must contain a mapping at the top level.", "<root>")
    return raw


def strip_private(raw: dict) -> dict:
    """Drop top-level keys starting with '_' (e.g. ``_zoom_meta``)."""
    return {k: v for k, v in raw.items() if not str(k).startswith("_")}


def _motion_with_defaults(entity: dict) -> dict:
    motion = copy.deepcopy(entity.get("motion") or {"type": "static"})
    motion.setdefault("type", "static")
    return motion


def resolve_config(raw: dict) -> dict:
    """Return a normalised deep copy of ``raw`` with all defaults made explicit.

    Two configs that differ only in explicit-vs-implicit defaults resolve to the
    same dict, so their fingerprints match.
    """
    r = copy.deepcopy(raw)
    r.setdefault("schema_version", SCENE_CONFIG_SCHEMA_VERSION)
    r.setdefault("sample_rate", 16000)
    r.setdefault("ism_order", 3)
    r.setdefault("speed_of_sound", 343.0)
    r["materials"] = r.get("materials") or {"default": "concrete"}
    r["materials"].setdefault("default", "concrete")
    r["impairments"] = r.get("impairments") or {}
    r["impairments"].setdefault("type", "none")

    motion = r.get("motion") or {}
    motion.setdefault("duration_s", DEFAULT_DURATION_S)
    motion.setdefault("tick_rate_hz", DEFAULT_TICK_RATE_HZ)
    r["motion"] = motion

    render = r.get("render") or {}
    render.setdefault("profile", RENDER_PROFILE)
    render.setdefault("tail", "keep")
    render.setdefault("allow_static_approximation", False)
    render.setdefault("storage_profile", "full")
    render.setdefault("fractional_delay", False)
    render.setdefault("band_reverb", False)
    r["render"] = render

    r["mix"] = r.get("mix") or {}

    qc = r.get("qc") or {}
    qc.setdefault("fail_on_clip", False)
    r["qc"] = qc

    room = r.get("room") or {}
    room.setdefault("type", "shoebox")
    room.setdefault("obstacles", [])
    r["room"] = room

    for i, src in enumerate(r.get("sources") or []):
        if src.get("position") is not None:
            src["position"] = position_to_list(src["position"], f"sources[{i}].position")
        src["motion"] = _motion_with_defaults(src)
        src.setdefault("onset_s", 0.0)
        src.setdefault("role", "speech")
    for i, rec in enumerate(r.get("receivers") or []):
        if rec.get("position") is not None:
            rec["position"] = position_to_list(rec["position"], f"receivers[{i}].position")
        rec["motion"] = _motion_with_defaults(rec)
        for k, v in RECEIVER_DEVICE_DEFAULTS.items():
            rec.setdefault(k, v)
    if r.get("receivers"):
        r.setdefault("reference_receiver", r["receivers"][0].get("receiver_id"))
    return r


# ---------------------------------------------------------------------------
# Render profile gate (F-09)
# ---------------------------------------------------------------------------

def check_profile(resolved: dict) -> Tuple[List[str], List[str], List[str]]:
    """Check ``resolved`` against the ``static_v1`` profile.

    Returns:
        (errors, approximations, warnings).  Non-empty ``errors`` means the
        scene must not be rendered.
    """
    errors: List[str] = []
    approx: List[str] = []
    warns: List[str] = []
    render = resolved.get("render", {})
    allow_approx = bool(render.get("allow_static_approximation", False))

    profile = render.get("profile", RENDER_PROFILE)
    if profile not in RENDER_PROFILES:
        errors.append(f"render.profile {profile!r} is not supported ({RENDER_PROFILES}).")
    if render.get("storage_profile", "full") not in STORAGE_PROFILES:
        errors.append(f"render.storage_profile must be one of {STORAGE_PROFILES}.")
    if render.get("tail", "keep") not in ("keep", "trim"):
        errors.append(f"render.tail must be 'keep' or 'trim', got {render.get('tail')!r}.")

    room_type = (resolved.get("room") or {}).get("type", "shoebox")
    if room_type != "shoebox":
        approx.append(f"room type {room_type!r} rendered with shoebox ISM over its bounding box")

    moving = []
    for kind, key in (("sources", "source_id"), ("receivers", "receiver_id")):
        for ent in resolved.get(kind) or []:
            mtype = (ent.get("motion") or {}).get("type", "static")
            if mtype not in STATIC_MOTION_TYPES:
                moving.append(f"{ent.get(key)}({mtype})")
    if moving and profile == "dynamic_v1":
        pass
    elif moving:
        if allow_approx:
            approx.append("moving entities rendered at tick 0: " + ", ".join(moving))
        else:
            errors.append(
                "moving entities are outside the static_v1 profile: " + ", ".join(moving)
                + " (use render.profile=dynamic_v1, or render.allow_static_approximation=true "
                "to render tick 0)."
            )

    from simulator.receiver_models import PATTERNS
    for rec in resolved.get("receivers") or []:
        if str(rec.get("pattern", "omni")) not in PATTERNS:
            errors.append(f"receiver {rec.get('receiver_id')}: pattern {rec.get('pattern')!r} not in {PATTERNS}.")
        if rec.get("binaural") and str(rec.get("pattern", "omni")) != "omni":
            errors.append(f"receiver {rec.get('receiver_id')}: binaural receivers take no pattern.")
        hrtf = rec.get("hrtf")
        if hrtf is not None:
            if not rec.get("binaural"):
                errors.append(f"receiver {rec.get('receiver_id')}: 'hrtf' needs 'binaural': true.")
            elif not isinstance(hrtf, dict) or not hrtf.get("sofa") or not os.path.isfile(str(hrtf["sofa"])):
                errors.append(f"receiver {rec.get('receiver_id')}: hrtf.sofa must be an existing SOFA file.")
        if rec.get("is_binaural"):
            errors.append(f"receiver {rec.get('receiver_id')}: use 'binaural': true.")

    roles = [str(s.get("role", "speech")) for s in resolved.get("sources") or []]
    bad_roles = sorted({r for r in roles if r not in SOURCE_ROLES})
    if bad_roles:
        errors.append(f"source role(s) {bad_roles} not in {SOURCE_ROLES}.")
    target_snr = (resolved.get("mix") or {}).get("target_snr_db")
    if target_snr is not None:
        if "speech" not in roles or not any(r in ("noise", "interference") for r in roles):
            errors.append("mix.target_snr_db needs at least one speech and one noise/interference source.")

    imp_type = (resolved.get("impairments") or {}).get("type", "none")
    if imp_type not in SUPPORTED_IMPAIRMENTS:
        errors.append(f"impairments.type {imp_type!r} not in {SUPPORTED_IMPAIRMENTS}.")

    from simulator.uf.w112_material import MaterialDB
    db = MaterialDB()
    for k, v in (resolved.get("materials") or {}).items():
        if k in ("stochastic_variation", "variation_sigma"):
            continue
        if isinstance(v, dict):
            a = v.get("alpha")
            if not (isinstance(a, (list, tuple)) and len(a) == 6 and all(0.0 <= float(x) <= 1.0 for x in a)):
                errors.append(f"materials.{k}: alpha must be 6 values in [0, 1].")
        elif str(v) not in db:
            errors.append(f"materials.{k}: unknown material {v!r}.")

    ref = resolved.get("reference_receiver")
    rec_ids = [r.get("receiver_id") for r in resolved.get("receivers") or []]
    if ref is not None and ref not in rec_ids:
        errors.append(f"reference_receiver {ref!r} is not a receiver_id.")

    if room_type == "shoebox":
        dims = (resolved.get("room") or {}).get("dimensions", {})
        try:
            L, H, W = float(dims["L"]), float(dims["H"]), float(dims["W"])
            for o in (resolved.get("room") or {}).get("obstacles", []):
                pos = o.get("position")
                if pos is not None and not (0 <= pos[0] <= L and 0 <= pos[1] <= H and 0 <= pos[2] <= W):
                    warns.append(f"obstacle {o.get('type')} at {pos} lies outside the room.")
        except (KeyError, TypeError, ValueError):
            pass
    return errors, approx, warns


# ---------------------------------------------------------------------------
# Fingerprint / signature (F-07, F-08)
# ---------------------------------------------------------------------------

def asset_hashes(resolved: dict, base_dir: Optional[str] = None) -> Dict[str, Optional[str]]:
    """SHA-256 of every referenced source signal file (None if missing)."""
    out: Dict[str, Optional[str]] = {}
    for src in resolved.get("sources") or []:
        path = src.get("signal_path")
        if not path:
            continue
        if base_dir and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        out[src["source_id"]] = sha256_file(path) if os.path.exists(path) else None
    return out


def render_fingerprint(
    raw: dict,
    assets: Optional[Dict[str, Optional[str]]] = None,
    base_dir: Optional[str] = None,
) -> str:
    """Identity of a render job.

    Includes the resolved config (minus scene_id / output_dir / private keys),
    the renderer version and input asset hashes.  Changing the display ID or
    output directory does not change it; changing the seed, geometry, device
    settings or an input file does.
    """
    resolved = resolve_config(strip_private(raw))
    if assets is None:
        assets = asset_hashes(resolved, base_dir)
    body = {k: v for k, v in resolved.items() if k not in _NON_RENDER_KEYS}
    # signal_path location is not part of identity, its content hash is.
    for src in body.get("sources") or []:
        src.pop("signal_path", None)
    payload = {"config": body, "renderer_version": RENDERER_VERSION, "assets": assets}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def scene_signature(raw: dict) -> str:
    """Short, human-comparable form of :func:`render_fingerprint`."""
    return render_fingerprint(raw)[:16]


# ---------------------------------------------------------------------------
# Editor merge (F-07)
# ---------------------------------------------------------------------------

def _unique_id(prefix: str, i: int, taken: set) -> str:
    cand = f"{prefix}{i}"
    k = 1
    while cand in taken:
        cand = f"{prefix}{i}-{k}"
        k += 1
    return cand


def _merge_entities(
    base_list: List[dict],
    n_edit: int,
    positions: Sequence[Sequence[float]],
    capacity: int,
    id_key: str,
    prefix: str,
) -> List[dict]:
    editable = [copy.deepcopy(e) for e in base_list[:capacity]]
    extra = [copy.deepcopy(e) for e in base_list[capacity:]]
    taken = {e.get(id_key) for e in editable + extra}
    out: List[dict] = []
    for i in range(int(n_edit)):
        pos = [float(v) for v in positions[i]]
        if i < len(editable):
            ent = editable[i]
            orig = ent.get("position")
            try:
                orig_l = position_to_list(orig, id_key) if orig is not None else None
            except ValidationError:
                orig_l = None
            # Keep the original value when the widget only shows it rounded.
            if orig_l is None or not np.allclose(orig_l, pos, atol=5e-3):
                ent["position"] = pos
                motion = ent.get("motion")
                if isinstance(motion, dict) and motion.get("type", "static") in STATIC_MOTION_TYPES:
                    motion.pop("position", None)
        else:
            new_id = _unique_id(prefix, i, taken)
            taken.add(new_id)
            ent = {id_key: new_id, "position": pos}
        out.append(ent)
    return out + extra


def apply_editor_overrides(
    base: Optional[dict],
    edits: dict,
    max_sources: int,
    max_receivers: int,
) -> dict:
    """Merge Scene-Editor values into ``base`` without losing anything else.

    ``edits`` keys: scene_id, seed, room_dims {L,W,H}, material, ism_order,
    sample_rate, n_sources, source_positions, n_receivers, receiver_positions,
    output_dir (optional).

    Rules: only edited fields change; entity IDs, obstacles, motion, device
    settings and private metadata are preserved.  Entities beyond the editor
    capacity (``max_sources`` / ``max_receivers``) are kept unchanged.  The
    editor count controls only the editable slots.
    """
    cfg = copy.deepcopy(base) if base else {
        "schema_version": SCENE_CONFIG_SCHEMA_VERSION,
        "room": {"type": "shoebox", "dimensions": {}},
        "materials": {"default": "concrete"},
        "sources": [],
        "receivers": [],
    }
    if "scene_id" in edits and edits["scene_id"]:
        cfg["scene_id"] = str(edits["scene_id"])
    if "seed" in edits and edits["seed"] is not None:
        cfg["seed"] = int(edits["seed"])
    if "room_dims" in edits:
        room = cfg.setdefault("room", {"type": "shoebox"})
        dims = room.setdefault("dimensions", {})
        for k in ("L", "W", "H"):
            new = float(edits["room_dims"][k])
            if k not in dims or not math.isclose(float(dims[k]), new, abs_tol=5e-3):
                dims[k] = new
    if edits.get("material"):
        mats = cfg.setdefault("materials", {})
        mats["default"] = edits["material"]
    for key in ("ism_order", "sample_rate"):
        if key in edits and edits[key] is not None:
            cfg[key] = int(edits[key])
    if "output_dir" in edits and edits["output_dir"]:
        cfg["output_dir"] = edits["output_dir"]
    if "n_sources" in edits:
        cfg["sources"] = _merge_entities(
            cfg.get("sources") or [], edits["n_sources"], edits["source_positions"],
            max_sources, "source_id", "s",
        )
    if "n_receivers" in edits:
        cfg["receivers"] = _merge_entities(
            cfg.get("receivers") or [], edits["n_receivers"], edits["receiver_positions"],
            max_receivers, "receiver_id", "r",
        )
    return cfg


def editor_view(cfg: dict, max_sources: int, max_receivers: int) -> dict:
    """Values the Scene Editor can show for ``cfg`` plus what it cannot show."""
    dims = (cfg.get("room") or {}).get("dimensions", {})
    mats = cfg.get("materials") or {}

    def _positions(ents, cap):
        out = []
        for e in ents[:cap]:
            try:
                out.append(position_to_list(e.get("position"), "position"))
            except ValidationError:
                out.append(None)  # motion-only entity: editor cannot show it
        return out

    sources = cfg.get("sources") or []
    receivers = cfg.get("receivers") or []
    return {
        "scene_id": cfg.get("scene_id", "scene_001"),
        "seed": int(cfg.get("seed", 42)),
        "room_dims": {k: float(dims.get(k, d)) for k, d in (("L", 5.0), ("W", 4.0), ("H", 3.0))},
        "material": mats.get("default", "concrete"),
        "ism_order": int(cfg.get("ism_order", 3)),
        "sample_rate": int(cfg.get("sample_rate", 16000)),
        "source_positions": _positions(sources, max_sources),
        "receiver_positions": _positions(receivers, max_receivers),
        "n_sources_total": len(sources),
        "n_receivers_total": len(receivers),
        "n_sources_hidden": max(0, len(sources) - max_sources),
        "n_receivers_hidden": max(0, len(receivers) - max_receivers),
        "n_obstacles": len((cfg.get("room") or {}).get("obstacles", [])),
        "per_surface_materials": sorted(k for k in mats if k != "default"),
    }


# ---------------------------------------------------------------------------
# Preflight (F-07, F-11)
# ---------------------------------------------------------------------------

def _estimate_rt60(resolved: dict) -> Optional[float]:
    try:
        from simulator.uf.w151_config import SceneConfigValidator as _V
        from simulator.if_modules.scene_world import SceneWorldBuilder
        from simulator.uf.w122_reverberation import estimate_sabine_rt60
        import warnings as _w
        cfg = _V().validate(strip_private(resolved))
        with _w.catch_warnings():
            _w.simplefilter("ignore")
            b = SceneWorldBuilder(cfg, seed=cfg.seed)
            room = b.build_room()
            mats = b.build_materials()
            return float(estimate_sabine_rt60(room.dimensions, mats))
    except Exception:
        return None


def preflight(raw: dict) -> dict:
    """Validate, resolve and gate a config before rendering.

    Returns a dict with keys: ok, errors, warnings, approximations, resolved,
    signature, fingerprint, workload.
    """
    report = {
        "ok": False, "errors": [], "warnings": [], "approximations": [],
        "resolved": None, "signature": None, "fingerprint": None, "workload": {},
    }
    try:
        clean = strip_private(raw)
        SceneConfigValidator().validate(clean)
        resolved = resolve_config(clean)
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        report["errors"].append(f"validation: {exc}")
        return report

    errors, approx, warns = check_profile(resolved)
    report["errors"].extend(errors)
    report["approximations"].extend(approx)
    report["warnings"].extend(warns)
    unknown = sorted(k for k in raw if k not in KNOWN_TOP_LEVEL_KEYS and not str(k).startswith("_"))
    if unknown:
        report["warnings"].append(f"unknown top-level keys ignored: {unknown}")
    for src in resolved.get("sources") or []:
        if src.get("signal_path") and not os.path.exists(src["signal_path"]):
            report["errors"].append(f"source {src['source_id']}: signal_path not found: {src['signal_path']}")

    fs = int(resolved["sample_rate"])
    duration = float(resolved["motion"]["duration_s"])
    S = len(resolved.get("sources") or [])
    C = len(resolved.get("receivers") or [])
    rt60 = _estimate_rt60(resolved)
    rir_s = min(max(3.0 * (rt60 if rt60 else 0.5), 0.5), MAX_RIR_DURATION_S)
    n_dry = int(round(duration * fs))
    L = int(rir_s * fs)
    T = n_dry + L - 1 if resolved["render"]["tail"] == "keep" else n_dry
    if resolved["render"].get("storage_profile", "full") == "training":
        n_floats = C * T + S * C * T
    else:
        n_floats = 2 * C * T + S * C * T + S * n_dry + S * C * L
    report["workload"] = {
        "n_sources": S, "n_receivers": C, "n_pairs": S * C,
        "duration_s": duration, "sabine_rt60_s": rt60, "rir_length_s": rir_s,
        "output_samples_per_channel": T, "estimated_bytes": int(4 * n_floats),
    }
    report["resolved"] = resolved
    report["fingerprint"] = render_fingerprint(raw)
    report["signature"] = report["fingerprint"][:16]
    report["ok"] = not report["errors"]
    return report
