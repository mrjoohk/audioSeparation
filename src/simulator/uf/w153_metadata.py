"""
UF-W153: Metadata Export and Dataset Manifest.

Implements UF-W153-01 through UF-W153-04:
  - export_scene_parameters
  - export_trajectories_and_events
  - export_acoustic_summary
  - write_scene_manifest
  - build_dataset_index
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_SRC = _HERE.parent.parent.parent  # .../src/
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from simulator.types import AcousticSummary, SceneConfig, SourceTrajectory, ReceiverTrajectory

# ---------------------------------------------------------------------------
# Schema version for manifests
# ---------------------------------------------------------------------------
MANIFEST_SCHEMA_VERSION: str = "1.0.0"


# ---------------------------------------------------------------------------
# Internal JSON encoder that handles numpy arrays gracefully
# ---------------------------------------------------------------------------

class _SafeEncoder(json.JSONEncoder):
    """JSON encoder that converts numpy types to plain Python types."""

    def default(self, obj):
        try:
            import numpy as np
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.bool_):
                return bool(obj)
        except ImportError:
            pass
        return super().default(obj)


def _write_json(data: dict, output_path: str) -> None:
    """Write *data* to *output_path* as UTF-8 indented JSON, creating parents."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, cls=_SafeEncoder, ensure_ascii=False)


# ---------------------------------------------------------------------------
# UF-W153-01: Scene parameter export
# ---------------------------------------------------------------------------


def export_scene_parameters(config: SceneConfig, output_path: str) -> dict:
    """Write scene-level configuration parameters to a JSON file.

    Fields written: scene_id, seed, room_type, room_dims, n_sources,
    n_receivers, sample_rate, ism_order.

    Args:
        config:      The validated SceneConfig for this scene.
        output_path: Destination .json file path.

    Returns:
        The exported dict (same content as the file).
    """
    room_dims = config.room.get("dimensions", {})
    data: dict = {
        "scene_id": config.scene_id,
        "seed": config.seed,
        "schema_version": config.schema_version,
        "room_type": config.room.get("type", "unknown"),
        "room_dims": room_dims,
        "n_sources": len(config.sources),
        "n_receivers": len(config.receivers),
        "sample_rate": config.sample_rate,
        "ism_order": config.ism_order,
        "speed_of_sound": config.speed_of_sound,
        "output_dir": config.output_dir,
    }
    _write_json(data, output_path)
    return data


# ---------------------------------------------------------------------------
# UF-W153-02: Trajectory and event export
# ---------------------------------------------------------------------------


def _tick_to_dict(tick) -> dict:
    """Convert a TickState to a plain dict safe for JSON serialisation."""
    d: dict = {
        "tick_id": int(tick.tick_id),
        "timestamp_s": float(tick.timestamp_s),
        "orientation": float(tick.orientation),
    }
    # position / velocity may be numpy arrays
    try:
        d["position"] = tick.position.tolist()
    except AttributeError:
        d["position"] = list(tick.position)
    try:
        d["velocity"] = tick.velocity.tolist()
    except AttributeError:
        d["velocity"] = list(tick.velocity)
    if tick.orientation_quat is not None:
        try:
            d["orientation_quat"] = tick.orientation_quat.tolist()
        except AttributeError:
            d["orientation_quat"] = list(tick.orientation_quat)
    return d


def export_trajectories_and_events(
    src_trajectories: Union[List[SourceTrajectory], Dict],
    rec_trajectories: Union[List[ReceiverTrajectory], Dict],
    event_timeline: Optional[List[dict]],
    output_path: str,
) -> dict:
    """Write source/receiver trajectories and optional event timeline to JSON.

    Trajectory format::

        {
          "source_trajectories": {
            "<source_id>": [{"tick_id":…, "timestamp_s":…, "position":…, "velocity":…}, …]
          },
          "receiver_trajectories": { … },
          "event_timeline": [ … ]   // omitted if None
        }

    Args:
        src_trajectories:  List[SourceTrajectory] or Dict[str, list-of-ticks].
        rec_trajectories:  List[ReceiverTrajectory] or Dict[str, list-of-ticks].
        event_timeline:    Optional list of event dicts.
        output_path:       Destination .json file path.

    Returns:
        The exported dict.
    """
    # Normalise source trajectories
    src_export: dict = {}
    if isinstance(src_trajectories, dict):
        src_export = src_trajectories
    else:
        for traj in src_trajectories:
            src_export[traj.source_id] = [_tick_to_dict(t) for t in traj.ticks]

    # Normalise receiver trajectories
    rec_export: dict = {}
    if isinstance(rec_trajectories, dict):
        rec_export = rec_trajectories
    else:
        for traj in rec_trajectories:
            rec_export[traj.receiver_id] = [_tick_to_dict(t) for t in traj.ticks]

    data: dict = {
        "source_trajectories": src_export,
        "receiver_trajectories": rec_export,
    }
    if event_timeline is not None:
        data["event_timeline"] = event_timeline

    _write_json(data, output_path)
    return data


# ---------------------------------------------------------------------------
# UF-W153-03: Acoustic summary export
# ---------------------------------------------------------------------------


def export_acoustic_summary(
    acoustic_summary: AcousticSummary,
    output_path: str,
) -> dict:
    """Write an AcousticSummary to JSON.

    Fields: scene_id, rt60_measured_s, drr_db, snr_db, doa_az_deg,
    doa_el_deg, sabine_rt60_s.

    Args:
        acoustic_summary: Populated AcousticSummary dataclass.
        output_path:      Destination .json file path.

    Returns:
        The exported dict.
    """
    data: dict = {
        "scene_id": acoustic_summary.scene_id,
        "rt60_measured_s": acoustic_summary.rt60_measured_s,
        "drr_db": acoustic_summary.drr_db,
        "snr_db": acoustic_summary.snr_db,
        "doa_az_deg": acoustic_summary.doa_az_deg,
        "doa_el_deg": acoustic_summary.doa_el_deg,
        "sabine_rt60_s": acoustic_summary.sabine_rt60_s,
    }
    _write_json(data, output_path)
    return data


# ---------------------------------------------------------------------------
# UF-W153-04: Scene manifest
# ---------------------------------------------------------------------------


def write_scene_manifest(
    scene_id: str,
    output_dir: str,
    audio_files: List[str],
    rir_files: List[str],
    metadata_json_path: str,
    acoustic_summary: AcousticSummary,
) -> dict:
    """Build and write the per-scene manifest JSON.

    The manifest is written to ``<output_dir>/<scene_id>/scene_manifest.json``.

    Manifest schema v1.0::

        {
          "schema_version": "1.0.0",
          "scene_id": str,
          "source_count": int,       // derived from acoustic_summary
          "channel_count": int,      // len(audio_files)
          "audio_files": [str, …],
          "rir_files": [str, …],
          "metadata_json_path": str,
          "acoustic_summary": {
            "RT60": float,
            "DRR": float,
            "SNR": float | null,
            "DOA_az": float | null,
            "DOA_el": float | null
          }
        }

    Missing audio/RIR paths trigger a warning but do NOT abort.

    Args:
        scene_id:           Unique scene identifier string.
        output_dir:         Root output directory; manifest is placed under
                            ``<output_dir>/<scene_id>/scene_manifest.json``.
        audio_files:        List of audio file paths (strings).
        rir_files:          List of RIR file paths (strings).
        metadata_json_path: Path to the scene parameter JSON.
        acoustic_summary:   AcousticSummary dataclass for this scene.

    Returns:
        The manifest dict (same content as the file).
    """
    # Validate audio_files existence (warn, don't fail)
    for af in audio_files:
        if not Path(af).exists():
            warnings.warn(
                f"Manifest audio file does not exist: {af}",
                UserWarning,
                stacklevel=2,
            )
    for rf in rir_files:
        if not Path(rf).exists():
            warnings.warn(
                f"Manifest RIR file does not exist: {rf}",
                UserWarning,
                stacklevel=2,
            )

    manifest: dict = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "scene_id": scene_id,
        "source_count": 1,          # single acoustic_summary covers one src/rec pair;
                                    # callers can override via the returned dict if needed
        "channel_count": len(audio_files),
        "audio_files": [str(f) for f in audio_files],
        "rir_files": [str(f) for f in rir_files],
        "metadata_json_path": str(metadata_json_path),
        "acoustic_summary": {
            "RT60": acoustic_summary.rt60_measured_s,
            "DRR": acoustic_summary.drr_db,
            "SNR": acoustic_summary.snr_db,
            "DOA_az": acoustic_summary.doa_az_deg,
            "DOA_el": acoustic_summary.doa_el_deg,
        },
    }

    manifest_path = Path(output_dir) / scene_id / "scene_manifest.json"
    _write_json(manifest, str(manifest_path))
    return manifest


# ---------------------------------------------------------------------------
# UF-W153-05 (bonus): Dataset index
# ---------------------------------------------------------------------------


def build_dataset_index(
    manifests: List[dict],
    output_path: str,
) -> dict:
    """Aggregate scene manifests into a single dataset_index.json.

    The index lists all scenes with their scene_id and manifest file path.
    If a manifest contains a ``_manifest_path`` key (injected by callers), it
    is used; otherwise the entry's scene_id is used as a placeholder.

    Fields::

        {
          "n_scenes": int,
          "created_at": "<ISO-8601 UTC timestamp>",
          "scenes": [
            {"scene_id": str, "manifest_path": str},
            …
          ]
        }

    Args:
        manifests:   List of manifest dicts (as returned by write_scene_manifest).
        output_path: Destination path for dataset_index.json.

    Returns:
        The index dict.
    """
    scenes_list = []
    for m in manifests:
        sid = m.get("scene_id", "unknown")
        # Support callers injecting the actual path via a private key
        mpath = m.get("_manifest_path", f"{sid}/scene_manifest.json")
        scenes_list.append({"scene_id": sid, "manifest_path": str(mpath)})

    index: dict = {
        "n_scenes": len(manifests),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenes": scenes_list,
    }

    _write_json(index, output_path)
    return index


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import os

    print("=== w153_metadata smoke test ===")

    from simulator.types import SceneConfig, AcousticSummary  # noqa: F811

    with tempfile.TemporaryDirectory() as tmpdir:

        # --- SceneConfig ---
        cfg = SceneConfig(
            scene_id="smoke_001",
            seed=7,
            schema_version="1.0.0",
            room={"type": "shoebox", "dimensions": {"L": 6.0, "W": 5.0, "H": 3.0}},
            materials={},
            sources=[
                {"source_id": "s1", "position": {"x": 2.0, "y": 1.5, "z": 3.0}},
                {"source_id": "s2", "position": {"x": 3.0, "y": 1.5, "z": 2.0}},
            ],
            receivers=[
                {"receiver_id": "r1", "position": {"x": 4.0, "y": 1.5, "z": 3.0}},
            ],
        )

        params_path = os.path.join(tmpdir, "smoke_001", "params.json")
        params = export_scene_parameters(cfg, params_path)
        print(f"  n_sources   : {params['n_sources']}")
        print(f"  n_receivers : {params['n_receivers']}")
        assert params["scene_id"] == "smoke_001"
        assert params["n_sources"] == 2

        # --- Trajectories (empty) ---
        traj_path = os.path.join(tmpdir, "smoke_001", "trajectories.json")
        traj = export_trajectories_and_events({}, {}, None, traj_path)
        assert "source_trajectories" in traj

        # --- Acoustic summary ---
        summ = AcousticSummary(
            scene_id="smoke_001",
            rt60_measured_s=0.45,
            drr_db=3.2,
            snr_db=30.0,
            doa_az_deg=45.0,
            doa_el_deg=10.0,
            sabine_rt60_s=0.50,
        )
        summ_path = os.path.join(tmpdir, "smoke_001", "acoustic_summary.json")
        summ_data = export_acoustic_summary(summ, summ_path)
        print(f"  RT60        : {summ_data['rt60_measured_s']}")
        assert summ_data["rt60_measured_s"] == 0.45

        # --- Manifest ---
        manifest = write_scene_manifest(
            scene_id="smoke_001",
            output_dir=tmpdir,
            audio_files=[],
            rir_files=[],
            metadata_json_path=params_path,
            acoustic_summary=summ,
        )
        assert "scene_id" in manifest
        assert manifest["acoustic_summary"]["RT60"] == 0.45
        print(f"  manifest keys: {list(manifest.keys())}")

        # --- Dataset index ---
        index = build_dataset_index([manifest], os.path.join(tmpdir, "dataset_index.json"))
        assert index["n_scenes"] == 1
        print(f"  dataset_index n_scenes: {index['n_scenes']}")

    print("  PASS")
