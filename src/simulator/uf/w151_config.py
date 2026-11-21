"""
UF-W151: Scene Configuration Loading, Validation, and Seed Derivation.

Implements UF-W151-01 through UF-W151-05:
  - SceneConfigValidator: validate raw config dicts → SceneConfig
  - load_config_from_file / save_config_to_file
  - derive_subsystem_seeds
"""
from __future__ import annotations

import json
import math
import re
import sys
import os
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from repo root or directly
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_SRC = _HERE.parent.parent.parent  # src/
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from simulator.types import (
    SceneConfig,
    VALID_SAMPLE_RATES,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCENE_CONFIG_SCHEMA_VERSION: str = "1.0.0"

# Entity IDs become file-name components (``reference__{src}__{rec}.wav``), so
# they must be filesystem-safe and must not contain the "__" separator.
ENTITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9.-]+(?:_[A-Za-z0-9.-]+)*$")
ENTITY_ID_MAX_LEN = 64

# Optional top-level keys carried through SceneConfig.extras (static_v1 contract).
EXTRA_TOP_LEVEL_KEYS = ("render", "qc", "reference_receiver")

_SUBSYSTEM_NAMES: List[str] = [
    "room",
    "material",
    "obstacle",
    "trajectory_src",
    "trajectory_rec",
    "noise",
    "codec",
]

# ---------------------------------------------------------------------------
# Custom Exception
# ---------------------------------------------------------------------------


class ValidationError(ValueError):
    """Raised when a scene config field is missing or invalid.

    The message always contains the dot-separated field path that failed.
    """

    def __init__(self, message: str, field_path: str = ""):
        self.field_path = field_path
        full_msg = f"[{field_path}] {message}" if field_path else message
        super().__init__(full_msg)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_field(d: dict, key: str, parent_path: str = "") -> object:
    """Return d[key], raising ValidationError if missing."""
    if key not in d:
        path = f"{parent_path}.{key}" if parent_path else key
        raise ValidationError(f"Required field '{key}' is missing.", field_path=path)
    return d[key]


def _require_type(value: object, expected_type, key: str) -> None:
    """Raise ValidationError if value is not of expected_type."""
    if not isinstance(value, expected_type):
        raise ValidationError(
            f"Expected {expected_type.__name__}, got {type(value).__name__}.",
            field_path=key,
        )


def position_to_list(pos, field_path: str) -> List[float]:
    """Normalise a position given as ``[x, y, z]`` or ``{"x":..,"y":..,"z":..}``.

    Raises ValidationError if the value is not three finite numbers.
    """
    if isinstance(pos, dict):
        try:
            pos = [pos["x"], pos["y"], pos["z"]]
        except KeyError as exc:
            raise ValidationError(
                f"Position dict must have keys x, y, z (missing {exc}).", field_path=field_path
            )
    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        raise ValidationError(
            "Position must be [x, y, z] or {x, y, z}.", field_path=field_path
        )
    out = []
    for v in pos:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            raise ValidationError(
                f"Position components must be finite numbers, got {pos!r}.",
                field_path=field_path,
            )
        out.append(float(v))
    return out


def _validate_entity_ids(entities: list, key: str, list_name: str) -> None:
    seen = {}
    for i, ent in enumerate(entities):
        eid = ent[key]
        path = f"{list_name}[{i}].{key}"
        if not eid or len(eid) > ENTITY_ID_MAX_LEN or not ENTITY_ID_PATTERN.match(eid):
            raise ValidationError(
                f"{key} {eid!r} must match {ENTITY_ID_PATTERN.pattern} "
                f"(letters, digits, '.', '-', single '_'; max {ENTITY_ID_MAX_LEN} chars).",
                field_path=path,
            )
        if eid in seen:
            raise ValidationError(
                f"Duplicate {key} {eid!r} (also at {list_name}[{seen[eid]}]).",
                field_path=path,
            )
        seen[eid] = i


def _validate_inside_shoebox(pos: List[float], dims: dict, field_path: str) -> None:
    """Y-up convention: x in [0, L], y in [0, H], z in [0, W]."""
    try:
        L, H, W = float(dims["L"]), float(dims["H"]), float(dims["W"])
    except (KeyError, TypeError, ValueError):
        return  # dimension errors are reported separately
    x, y, z = pos
    if not (0.0 < x < L and 0.0 < y < H and 0.0 < z < W):
        raise ValidationError(
            f"Position {pos} lies outside the room interior "
            f"(x in (0, {L}), y in (0, {H}), z in (0, {W}); Y-up).",
            field_path=field_path,
        )


# ---------------------------------------------------------------------------
# Schema version comparison
# ---------------------------------------------------------------------------


def _parse_semver(version_str: str):
    """Parse 'MAJOR.MINOR.PATCH' → (int, int, int). Raises ValidationError on bad format."""
    parts = str(version_str).split(".")
    if len(parts) != 3:
        raise ValidationError(
            f"Invalid semantic version format: '{version_str}'. Expected MAJOR.MINOR.PATCH",
            field_path="schema_version",
        )
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise ValidationError(
            f"Non-integer component in version '{version_str}'.",
            field_path="schema_version",
        )


# ---------------------------------------------------------------------------
# SceneConfigValidator
# ---------------------------------------------------------------------------


class SceneConfigValidator:
    """Validate raw config dicts and produce typed SceneConfig objects.

    All validation is in-memory (no I/O) and should complete in < 10 ms.
    """

    # ------------------------------------------------------------------
    def validate_schema_version(self, config_version: str) -> bool:
        """Check config_version against SCENE_CONFIG_SCHEMA_VERSION.

        - MAJOR mismatch → raises ValidationError
        - MINOR or PATCH mismatch → emits UserWarning, returns False
        - Exact match → returns True
        """
        cfg_major, cfg_minor, cfg_patch = _parse_semver(config_version)
        ref_major, ref_minor, ref_patch = _parse_semver(SCENE_CONFIG_SCHEMA_VERSION)

        if cfg_major != ref_major:
            raise ValidationError(
                f"Schema major version mismatch: config is {config_version!r}, "
                f"simulator expects {SCENE_CONFIG_SCHEMA_VERSION!r}. "
                "Major versions are incompatible.",
                field_path="schema_version",
            )

        if (cfg_minor, cfg_patch) != (ref_minor, ref_patch):
            warnings.warn(
                f"Schema version mismatch (minor/patch): config={config_version!r}, "
                f"simulator={SCENE_CONFIG_SCHEMA_VERSION!r}. "
                "Proceeding with best-effort compatibility.",
                UserWarning,
                stacklevel=3,
            )
            return False

        return True

    # ------------------------------------------------------------------
    def validate(self, raw_config: dict) -> SceneConfig:
        """Validate *raw_config* and return a populated SceneConfig.

        Required top-level fields: scene_id, seed, room, sources, receivers.
        Optional fields use defaults when absent.

        Raises ValidationError with the offending field path in the message.
        """
        if not isinstance(raw_config, dict):
            raise ValidationError(
                "Config must be a dict, got: " + type(raw_config).__name__,
                field_path="<root>",
            )

        # ---- schema_version (optional — warn if absent, validate if present) ----
        schema_version = raw_config.get("schema_version", SCENE_CONFIG_SCHEMA_VERSION)
        self.validate_schema_version(str(schema_version))

        # ---- Required top-level scalar fields ----
        scene_id = _require_field(raw_config, "scene_id", "")
        _require_type(scene_id, str, "scene_id")
        if not scene_id.strip():
            raise ValidationError("scene_id must be a non-empty string.", field_path="scene_id")

        seed = _require_field(raw_config, "seed", "")
        if not isinstance(seed, int):
            raise ValidationError(
                f"seed must be an integer, got {type(seed).__name__}.", field_path="seed"
            )

        # ---- room ----
        room_raw = _require_field(raw_config, "room", "")
        _require_type(room_raw, dict, "room")
        _require_field(room_raw, "type", "room")
        _require_field(room_raw, "dimensions", "room")
        room_dims = room_raw["dimensions"]
        if not isinstance(room_dims, dict):
            raise ValidationError(
                "room.dimensions must be a dict.", field_path="room.dimensions"
            )

        # ---- sources ----
        sources_raw = _require_field(raw_config, "sources", "")
        _require_type(sources_raw, list, "sources")
        if len(sources_raw) < 1:
            raise ValidationError(
                "At least one source is required.", field_path="sources"
            )
        for i, src in enumerate(sources_raw):
            if not isinstance(src, dict):
                raise ValidationError(
                    f"sources[{i}] must be a dict.", field_path=f"sources[{i}]"
                )
            _require_field(src, "source_id", f"sources[{i}]")
            _require_type(src["source_id"], str, f"sources[{i}].source_id")
            if "position" not in src and "motion" not in src:
                raise ValidationError(
                    "Each source must have 'position' or 'motion'.",
                    field_path=f"sources[{i}]",
                )

        # ---- receivers ----
        receivers_raw = _require_field(raw_config, "receivers", "")
        _require_type(receivers_raw, list, "receivers")
        if len(receivers_raw) < 1:
            raise ValidationError(
                "At least one receiver is required.", field_path="receivers"
            )
        for i, rec in enumerate(receivers_raw):
            if not isinstance(rec, dict):
                raise ValidationError(
                    f"receivers[{i}] must be a dict.", field_path=f"receivers[{i}]"
                )
            _require_field(rec, "receiver_id", f"receivers[{i}]")
            _require_type(rec["receiver_id"], str, f"receivers[{i}].receiver_id")
            if "position" not in rec and "motion" not in rec:
                raise ValidationError(
                    "Each receiver must have 'position' or 'motion'.",
                    field_path=f"receivers[{i}]",
                )

        # ---- IDs: unique and filesystem-safe ----
        _validate_entity_ids(sources_raw, "source_id", "sources")
        _validate_entity_ids(receivers_raw, "receiver_id", "receivers")

        # ---- room dimensions and positions ----
        room_type = room_raw["type"]
        if room_type in ("shoebox", "corridor", "hall"):
            for k in ("L", "W", "H"):
                v = room_dims.get(k)
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not (
                    math.isfinite(float(v)) and float(v) > 0
                ):
                    raise ValidationError(
                        f"room.dimensions.{k} must be a positive finite number, got {v!r}.",
                        field_path=f"room.dimensions.{k}",
                    )
        for list_name, entities in (("sources", sources_raw), ("receivers", receivers_raw)):
            for i, ent in enumerate(entities):
                if "position" in ent and ent["position"] is not None:
                    pos = position_to_list(ent["position"], f"{list_name}[{i}].position")
                    if room_type == "shoebox":
                        _validate_inside_shoebox(pos, room_dims, f"{list_name}[{i}].position")

        # ---- impairments ----
        imp = raw_config.get("impairments") or {}
        if not isinstance(imp, dict):
            raise ValidationError("impairments must be a dict.", field_path="impairments")
        per = imp.get("packet_error_rate")
        if per is not None and not (0.0 <= float(per) <= (1.0 if imp.get("allow_stress") else 0.2)):
            raise ValidationError(
                f"packet_error_rate={per} outside [0, 0.2] (set allow_stress for stress tests).",
                field_path="impairments.packet_error_rate",
            )
        arr = imp.get("array_errors")
        if arr is not None:
            if not isinstance(arr, dict):
                raise ValidationError("array_errors must be a dict.", field_path="impairments.array_errors")
            sig = float(arr.get("position_sigma_m", 0.0))
            skew = arr.get("max_clock_skew_samples", 0)
            if not (math.isfinite(sig) and 0.0 <= sig <= 0.1):
                raise ValidationError(
                    f"position_sigma_m={sig} outside [0, 0.1] m.",
                    field_path="impairments.array_errors.position_sigma_m",
                )
            if isinstance(skew, bool) or not isinstance(skew, int) or not (0 <= skew <= 64):
                raise ValidationError(
                    f"max_clock_skew_samples={skew!r} must be an int in [0, 64].",
                    field_path="impairments.array_errors.max_clock_skew_samples",
                )

        # ---- sample_rate ----
        sample_rate: int = raw_config.get("sample_rate", 16000)
        if not isinstance(sample_rate, int):
            raise ValidationError(
                f"sample_rate must be an integer, got {type(sample_rate).__name__}.",
                field_path="sample_rate",
            )
        if sample_rate not in VALID_SAMPLE_RATES:
            raise ValidationError(
                f"sample_rate={sample_rate} is not in the set of valid rates "
                f"{sorted(VALID_SAMPLE_RATES)}.",
                field_path="sample_rate",
            )

        # ---- ism_order ----
        ism_order: int = raw_config.get("ism_order", 3)
        if not isinstance(ism_order, int):
            raise ValidationError(
                f"ism_order must be an integer, got {type(ism_order).__name__}.",
                field_path="ism_order",
            )
        if not (1 <= ism_order <= 10):
            raise ValidationError(
                f"ism_order={ism_order} is out of range [1, 10].",
                field_path="ism_order",
            )

        # ---- Optional top-level fields ----
        materials: dict = raw_config.get("materials", {})
        motion: Optional[dict] = raw_config.get("motion", None)
        impairments: Optional[dict] = raw_config.get("impairments", None)
        output_dir: str = raw_config.get("output_dir", "output")
        speed_of_sound: float = float(raw_config.get("speed_of_sound", 343.0))

        return SceneConfig(
            scene_id=scene_id,
            seed=seed,
            schema_version=str(schema_version),
            room=room_raw,
            materials=materials,
            sources=sources_raw,
            receivers=receivers_raw,
            motion=motion,
            impairments=impairments,
            output_dir=output_dir,
            sample_rate=sample_rate,
            ism_order=ism_order,
            speed_of_sound=speed_of_sound,
            extras={k: raw_config[k] for k in EXTRA_TOP_LEVEL_KEYS if k in raw_config},
        )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_config_from_file(path: str) -> dict:
    """Load a scene config from a .json or .yaml file.

    Returns the raw dict (not validated). Call SceneConfigValidator.validate()
    on the result to obtain a SceneConfig.

    Raises:
        FileNotFoundError: if path does not exist.
        ImportError: if a .yaml file is given and PyYAML is not installed.
        ValueError: if the file extension is unsupported.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    suffix = p.suffix.lower()

    if suffix == ".json":
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    if suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to load .yaml config files. "
                "Install it with:  pip install pyyaml"
            ) from exc
        with p.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)

    raise ValueError(
        f"Unsupported config file extension '{suffix}'. "
        "Supported formats: .json, .yaml, .yml"
    )


def save_config_to_file(config: SceneConfig, path: str) -> None:
    """Serialize a SceneConfig dataclass to a JSON file (UTF-8, indented).

    The parent directory is created if it does not exist.
    """
    import dataclasses

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Convert dataclass → dict; numpy arrays become lists automatically via
    # a custom encoder because json.dumps default doesn't handle ndarray.
    raw = scene_config_to_dict(config)

    class _NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            try:
                import numpy as np  # noqa: F401
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                if isinstance(obj, (np.integer,)):
                    return int(obj)
                if isinstance(obj, (np.floating,)):
                    return float(obj)
            except ImportError:
                pass
            return super().default(obj)

    with p.open("w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=2, cls=_NumpyEncoder)


# ---------------------------------------------------------------------------
# Seed derivation
# ---------------------------------------------------------------------------


def derive_subsystem_seeds(
    global_seed: int,
    subsystem_names: Optional[List[str]] = None,
) -> Dict[str, int]:
    """Derive per-subsystem seeds from a global integer seed.

    Formula: seed_i = hash(str(global_seed) + name) & 0x7FFFFFFF

    The result is deterministic and platform-independent because we use
    Python's built-in hash() on a fixed string — but note that Python's
    hash randomisation (PYTHONHASHSEED) can affect str hashing in Python 3.3+.
    We therefore use hashlib.sha256 for cross-process reproducibility.

    Args:
        global_seed: The global scene seed (int).
        subsystem_names: Names to derive seeds for.
            Defaults to the canonical seven subsystems.

    Returns:
        Dict mapping each subsystem name to a non-negative 31-bit integer seed.
    """
    import hashlib

    if subsystem_names is None:
        subsystem_names = _SUBSYSTEM_NAMES

    result: Dict[str, int] = {}
    for name in subsystem_names:
        raw = (str(global_seed) + name).encode("utf-8")
        digest = hashlib.sha256(raw).digest()
        # Take the first 4 bytes as a little-endian uint32, then mask to 31 bits
        int_val = int.from_bytes(digest[:4], byteorder="little") & 0x7FFFFFFF
        result[name] = int_val

    return result


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== w151_config smoke test ===")

    _minimal = {
        "scene_id": "smoke_001",
        "seed": 42,
        "room": {
            "type": "shoebox",
            "dimensions": {"L": 6.0, "W": 4.0, "H": 3.0},
        },
        "sources": [
            {"source_id": "s1", "position": {"x": 2.0, "y": 1.5, "z": 2.0}},
        ],
        "receivers": [
            {"receiver_id": "r1", "position": {"x": 4.0, "y": 1.5, "z": 2.0}},
        ],
        "sample_rate": 16000,
        "ism_order": 3,
    }

    validator = SceneConfigValidator()
    cfg = validator.validate(_minimal)
    print(f"  scene_id   : {cfg.scene_id}")
    print(f"  seed       : {cfg.seed}")
    print(f"  sample_rate: {cfg.sample_rate}")
    print(f"  ism_order  : {cfg.ism_order}")

    seeds = derive_subsystem_seeds(cfg.seed)
    print(f"  subsystem seeds (first 3): "
          f"{dict(list(seeds.items())[:3])}")

    # Version checks
    ok = validator.validate_schema_version("1.0.0")
    print(f"  version 1.0.0 match: {ok}")

    try:
        validator.validate_schema_version("2.0.0")
    except ValidationError as e:
        print(f"  version 2.0.0 correctly raised: {e}")

    print("  PASS")


def scene_config_to_dict(config: SceneConfig) -> dict:
    """Inverse of :meth:`SceneConfigValidator.validate`: SceneConfig → raw dict.

    ``extras`` (render / qc / reference_receiver) are flattened back to the top
    level so that the result validates to an equal SceneConfig.
    """
    import copy
    import dataclasses
    raw = dataclasses.asdict(config)
    extras = raw.pop("extras", None) or {}
    for k, v in extras.items():
        raw[k] = copy.deepcopy(v)
    return raw
