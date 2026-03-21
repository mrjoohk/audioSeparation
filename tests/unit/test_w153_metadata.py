"""
Unit tests for UF-W153: Metadata Export and Dataset Manifest.

Tests:
  - test_manifest_schema_fields
  - test_manifest_acoustic_summary
  - test_dataset_index_count
  - test_export_scene_params_fields
"""
from __future__ import annotations

import json
import sys
import tempfile
import os
from pathlib import Path
from typing import List

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

from simulator.types import AcousticSummary, SceneConfig  # noqa: E402
from simulator.uf.w153_metadata import (  # noqa: E402
    MANIFEST_SCHEMA_VERSION,
    build_dataset_index,
    export_acoustic_summary,
    export_scene_parameters,
    export_trajectories_and_events,
    write_scene_manifest,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_config(
    scene_id: str = "test_001",
    n_sources: int = 2,
    n_receivers: int = 1,
) -> SceneConfig:
    """Create a minimal SceneConfig for testing."""
    sources = [
        {"source_id": f"s{i}", "position": {"x": float(i), "y": 1.5, "z": 2.0}}
        for i in range(n_sources)
    ]
    receivers = [
        {"receiver_id": f"r{i}", "position": {"x": 4.0, "y": 1.5, "z": float(i)}}
        for i in range(n_receivers)
    ]
    return SceneConfig(
        scene_id=scene_id,
        seed=7,
        schema_version="1.0.0",
        room={"type": "shoebox", "dimensions": {"L": 6.0, "W": 5.0, "H": 3.0}},
        materials={},
        sources=sources,
        receivers=receivers,
        sample_rate=16000,
        ism_order=3,
    )


def _make_acoustic_summary(
    scene_id: str = "test_001",
    rt60: float = 0.45,
    drr: float = 3.2,
    snr: float = 30.0,
    doa_az: float = 45.0,
    doa_el: float = 10.0,
    sabine_rt60: float = 0.50,
) -> AcousticSummary:
    return AcousticSummary(
        scene_id=scene_id,
        rt60_measured_s=rt60,
        drr_db=drr,
        snr_db=snr,
        doa_az_deg=doa_az,
        doa_el_deg=doa_el,
        sabine_rt60_s=sabine_rt60,
    )


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestExportSceneParameters:

    def test_export_scene_params_fields(self):
        """Exported JSON must contain all required metadata fields."""
        cfg = _make_config("scene_params_test", n_sources=2, n_receivers=1)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "params.json")
            result = export_scene_parameters(cfg, out_path)

        # Check returned dict
        required_fields = [
            "scene_id", "seed", "room_type", "room_dims",
            "n_sources", "n_receivers", "sample_rate", "ism_order",
        ]
        for field in required_fields:
            assert field in result, f"Missing field '{field}' in export_scene_parameters result"

        assert result["scene_id"] == "scene_params_test"
        assert result["n_sources"] == 2
        assert result["n_receivers"] == 1
        assert result["sample_rate"] == 16000
        assert result["ism_order"] == 3

    def test_export_scene_params_file_created(self):
        """export_scene_parameters must write a readable JSON file."""
        cfg = _make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "params.json")
            export_scene_parameters(cfg, out_path)

            assert Path(out_path).exists(), "params.json not created"
            with open(out_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)

        assert loaded["scene_id"] == cfg.scene_id

    def test_export_creates_parent_dirs(self):
        """Parent directories should be created if they don't exist."""
        cfg = _make_config()

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "deep", "nested", "params.json")
            export_scene_parameters(cfg, out_path)
            assert Path(out_path).exists()


class TestExportTrajectoriesAndEvents:

    def test_empty_trajectories(self):
        """Exporting empty trajectories should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "traj.json")
            result = export_trajectories_and_events({}, {}, None, out_path)

        assert "source_trajectories" in result
        assert "receiver_trajectories" in result
        assert "event_timeline" not in result   # None → omitted

    def test_event_timeline_included(self):
        """If event_timeline is not None, it must appear in the output."""
        events = [{"tick_id": 0, "event": "start"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "traj.json")
            result = export_trajectories_and_events({}, {}, events, out_path)

        assert "event_timeline" in result
        assert result["event_timeline"] == events

    def test_dict_trajectories_preserved(self):
        """Dict-based trajectories should be written as-is."""
        src_traj = {"s1": [{"tick_id": 0, "timestamp_s": 0.0, "position": [1, 1, 1], "velocity": [0, 0, 0]}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "traj.json")
            result = export_trajectories_and_events(src_traj, {}, None, out_path)

        assert "s1" in result["source_trajectories"]


class TestExportAcousticSummary:

    def test_acoustic_summary_fields(self):
        """Exported acoustic summary must contain all AcousticSummary fields."""
        summ = _make_acoustic_summary()

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "summary.json")
            result = export_acoustic_summary(summ, out_path)

        required = [
            "scene_id", "rt60_measured_s", "drr_db",
            "snr_db", "doa_az_deg", "doa_el_deg", "sabine_rt60_s",
        ]
        for field in required:
            assert field in result, f"Missing '{field}' in acoustic summary export"

    def test_acoustic_summary_values(self):
        """Values in the exported dict must match the input AcousticSummary."""
        summ = _make_acoustic_summary(rt60=0.88, drr=-2.5, snr=25.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "summary.json")
            result = export_acoustic_summary(summ, out_path)

        assert result["rt60_measured_s"] == pytest.approx(0.88)
        assert result["drr_db"] == pytest.approx(-2.5)
        assert result["snr_db"] == pytest.approx(25.0)


class TestWriteSceneManifest:

    def test_manifest_schema_fields(self):
        """Manifest dict must contain all required schema v1.0 keys."""
        summ = _make_acoustic_summary()

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = write_scene_manifest(
                scene_id="m_test_001",
                output_dir=tmpdir,
                audio_files=[],
                rir_files=[],
                metadata_json_path=os.path.join(tmpdir, "params.json"),
                acoustic_summary=summ,
            )

        required_keys = [
            "schema_version",
            "scene_id",
            "source_count",
            "channel_count",
            "audio_files",
            "rir_files",
            "metadata_json_path",
            "acoustic_summary",
        ]
        for key in required_keys:
            assert key in manifest, f"Missing required manifest key: '{key}'"

    def test_manifest_acoustic_summary(self):
        """manifest['acoustic_summary']['RT60'] must match input rt60_measured_s."""
        rt60_value = 0.73
        summ = _make_acoustic_summary(rt60=rt60_value)

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = write_scene_manifest(
                scene_id="m_test_002",
                output_dir=tmpdir,
                audio_files=[],
                rir_files=[],
                metadata_json_path=os.path.join(tmpdir, "params.json"),
                acoustic_summary=summ,
            )

        assert "acoustic_summary" in manifest
        assert manifest["acoustic_summary"]["RT60"] == pytest.approx(rt60_value), (
            f"manifest RT60={manifest['acoustic_summary']['RT60']} "
            f"!= expected {rt60_value}"
        )

    def test_manifest_schema_version(self):
        """manifest['schema_version'] must be '1.0.0'."""
        summ = _make_acoustic_summary()

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = write_scene_manifest(
                scene_id="m_test_003",
                output_dir=tmpdir,
                audio_files=[],
                rir_files=[],
                metadata_json_path=os.path.join(tmpdir, "params.json"),
                acoustic_summary=summ,
            )

        assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION

    def test_manifest_file_created(self):
        """write_scene_manifest must write scene_manifest.json to the correct path."""
        summ = _make_acoustic_summary()

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = write_scene_manifest(
                scene_id="m_file_test",
                output_dir=tmpdir,
                audio_files=[],
                rir_files=[],
                metadata_json_path=os.path.join(tmpdir, "params.json"),
                acoustic_summary=summ,
            )
            expected_path = Path(tmpdir) / "m_file_test" / "scene_manifest.json"
            assert expected_path.exists(), f"Manifest not found at {expected_path}"

    def test_manifest_audio_files_tracked(self):
        """audio_files and rir_files lists must appear in the manifest."""
        summ = _make_acoustic_summary()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create dummy files so warning isn't triggered (optional)
            audio = [os.path.join(tmpdir, "ch0.wav")]
            rir = [os.path.join(tmpdir, "rir0.npy")]

            manifest = write_scene_manifest(
                scene_id="m_files_test",
                output_dir=tmpdir,
                audio_files=audio,
                rir_files=rir,
                metadata_json_path=os.path.join(tmpdir, "params.json"),
                acoustic_summary=summ,
            )

        assert manifest["audio_files"] == audio
        assert manifest["rir_files"] == rir
        assert manifest["channel_count"] == 1


class TestBuildDatasetIndex:

    def test_dataset_index_count(self):
        """5 manifests must produce dataset_index with n_scenes=5."""
        manifests = [
            {"scene_id": f"scene_{i:03d}"}
            for i in range(5)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = os.path.join(tmpdir, "dataset_index.json")
            index = build_dataset_index(manifests, index_path)

        assert index["n_scenes"] == 5, (
            f"Expected n_scenes=5, got {index['n_scenes']}"
        )

    def test_dataset_index_scenes_list(self):
        """dataset_index must contain a 'scenes' list with one entry per manifest."""
        manifests = [{"scene_id": f"s{i}"} for i in range(3)]

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = os.path.join(tmpdir, "dataset_index.json")
            index = build_dataset_index(manifests, index_path)

        assert "scenes" in index
        assert len(index["scenes"]) == 3

    def test_dataset_index_file_written(self):
        """build_dataset_index must write a valid JSON file."""
        manifests = [{"scene_id": "only_one"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = os.path.join(tmpdir, "dataset_index.json")
            build_dataset_index(manifests, index_path)
            assert Path(index_path).exists()
            with open(index_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)

        assert loaded["n_scenes"] == 1

    def test_dataset_index_has_created_at(self):
        """dataset_index must include a 'created_at' ISO timestamp."""
        manifests = [{"scene_id": "ts_test"}]

        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = os.path.join(tmpdir, "dataset_index.json")
            index = build_dataset_index(manifests, index_path)

        assert "created_at" in index
        # Should be parseable as ISO 8601
        from datetime import datetime
        dt = datetime.fromisoformat(index["created_at"].replace("Z", "+00:00"))
        assert dt is not None

    def test_dataset_index_zero_scenes(self):
        """Empty manifests list should produce n_scenes=0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_path = os.path.join(tmpdir, "dataset_index.json")
            index = build_dataset_index([], index_path)

        assert index["n_scenes"] == 0
        assert index["scenes"] == []
