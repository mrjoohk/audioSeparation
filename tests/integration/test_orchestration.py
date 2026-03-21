"""Integration tests for IF-W151..W155: Simulator Orchestration."""
import os
import json
import pytest
import numpy as np

from simulator.if_modules.orchestration import SimulatorOrchestrator, simulate_scene
from simulator.uf.w151_config import SceneConfigValidator, ValidationError
from simulator.types import SceneConfig


MINIMAL_CONFIG_DICT = {
    "scene_id": "it_orch_001",
    "seed": 42,
    "schema_version": "1.0.0",
    "room": {"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
    "materials": {"default": "concrete"},
    "sources": [{"source_id": "s0", "position": [1.0, 1.0, 1.0]}],
    "receivers": [{"receiver_id": "r0", "position": [3.0, 1.0, 3.0]}],
    "sample_rate": 16000,
    "ism_order": 2,
}


def make_config(output_dir: str) -> SceneConfig:
    raw = dict(MINIMAL_CONFIG_DICT)
    raw["output_dir"] = output_dir
    return SceneConfigValidator().validate(raw)


# ---------------------------------------------------------------------------
# Config validation tests
# ---------------------------------------------------------------------------

def test_config_load_and_validate():
    """Minimal config dict → SceneConfig without error."""
    orch = SimulatorOrchestrator(MINIMAL_CONFIG_DICT, output_dir="output_test")
    config = orch.load_and_validate_config()
    assert config.scene_id == "it_orch_001"
    assert config.seed == 42
    assert config.sample_rate == 16000


def test_invalid_config_raises():
    """Config missing required field → ValidationError."""
    bad = {k: v for k, v in MINIMAL_CONFIG_DICT.items() if k != "scene_id"}
    orch = SimulatorOrchestrator(bad, output_dir="output_test")
    with pytest.raises(ValidationError):
        orch.load_and_validate_config()


def test_invalid_sample_rate_raises():
    """Unsupported sample rate → ValidationError."""
    bad = {**MINIMAL_CONFIG_DICT, "sample_rate": 12345}
    orch = SimulatorOrchestrator(bad, output_dir="output_test")
    with pytest.raises(ValidationError):
        orch.load_and_validate_config()


# ---------------------------------------------------------------------------
# simulate_scene tests
# ---------------------------------------------------------------------------

def test_simulate_scene_completes(tmp_path):
    """simulate_scene() should complete and return status='completed'."""
    config = make_config(str(tmp_path))
    result = simulate_scene(config)
    assert result["status"] == "completed"
    assert result["scene_id"] == "it_orch_001"
    assert result["elapsed_s"] > 0.0


def test_manifest_written(tmp_path):
    """simulate_scene() should create scene_manifest.json."""
    config = make_config(str(tmp_path))
    result = simulate_scene(config)
    manifest_path = result["manifest_path"]
    assert os.path.exists(manifest_path), f"Manifest not found at {manifest_path}"

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    assert "scene_id" in manifest
    assert manifest["scene_id"] == "it_orch_001"
    assert "audio_files" in manifest
    assert "acoustic_summary" in manifest


def test_acoustic_summary_rt60_plausible(tmp_path):
    """Acoustic summary RT60 should be in [0.01, 10.0] s."""
    config = make_config(str(tmp_path))
    result = simulate_scene(config)
    rt60 = result["acoustic_summary"].rt60_measured_s
    assert 0.01 <= rt60 <= 10.0, f"RT60={rt60:.3f} s outside plausible range"


def test_audio_files_created(tmp_path):
    """simulate_scene() should create non-empty WAV files for each receiver."""
    config = make_config(str(tmp_path))
    result = simulate_scene(config)
    manifest_path = result["manifest_path"]
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    for wav_path in manifest.get("audio_files", []):
        # Paths in manifest may be absolute or relative; check both
        if not os.path.isabs(wav_path):
            wav_path = os.path.join(str(tmp_path), wav_path)
        assert os.path.exists(wav_path), f"Audio file missing: {wav_path}"
        assert os.path.getsize(wav_path) > 44, f"Audio file too small: {wav_path}"


def test_orchestrator_export_results(tmp_path):
    """export_results() should create acoustic_summary.json."""
    from simulator.types import AcousticSummary
    orch = SimulatorOrchestrator(MINIMAL_CONFIG_DICT, output_dir=str(tmp_path))
    summary = AcousticSummary(
        scene_id="it_orch_001",
        rt60_measured_s=0.4,
        drr_db=5.0,
        snr_db=30.0,
        doa_az_deg=45.0,
        doa_el_deg=0.0,
    )
    manifest = orch.export_results(
        scene_id="it_orch_001",
        audio_files=[],
        rir_files=[],
        acoustic_summary=summary,
    )
    assert "scene_id" in manifest
    assert manifest["acoustic_summary"]["RT60"] == pytest.approx(0.4, abs=1e-6)
