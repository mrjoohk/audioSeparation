"""
Unit tests for UF-W151: Scene Configuration Loading, Validation, Seed Derivation.

Tests:
  - test_valid_config
  - test_missing_scene_id_raises
  - test_invalid_sample_rate_raises
  - test_invalid_ism_order_raises
  - test_schema_version_major_mismatch
  - test_derive_seeds_deterministic
  - test_derive_seeds_unique
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — find src/ regardless of how pytest is invoked
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent          # tests/unit/
_REPO_ROOT = _TESTS_DIR.parent.parent                  # W100000/
_SRC = _REPO_ROOT / "src"
for _p in (_SRC, _REPO_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from simulator.uf.w151_config import (  # noqa: E402
    SCENE_CONFIG_SCHEMA_VERSION,
    SceneConfigValidator,
    ValidationError,
    derive_subsystem_seeds,
)
from simulator.types import SceneConfig, VALID_SAMPLE_RATES  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture: minimal valid raw config dict
# ---------------------------------------------------------------------------

def _minimal_raw() -> dict:
    """Return a minimal, fully valid raw config dict."""
    return {
        "scene_id": "test_scene_001",
        "seed": 42,
        "room": {
            "type": "shoebox",
            "dimensions": {"L": 6.0, "W": 5.0, "H": 3.0},
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSceneConfigValidator:

    def setup_method(self):
        self.validator = SceneConfigValidator()

    # -----------------------------------------------------------------------
    def test_valid_config(self):
        """A complete minimal config dict should produce a valid SceneConfig."""
        raw = _minimal_raw()
        cfg = self.validator.validate(raw)

        assert isinstance(cfg, SceneConfig)
        assert cfg.scene_id == "test_scene_001"
        assert cfg.seed == 42
        assert cfg.sample_rate == 16000
        assert cfg.ism_order == 3
        assert len(cfg.sources) == 1
        assert len(cfg.receivers) == 1
        assert cfg.room["type"] == "shoebox"

    # -----------------------------------------------------------------------
    def test_missing_scene_id_raises(self):
        """Removing scene_id must raise ValidationError mentioning 'scene_id'."""
        raw = _minimal_raw()
        del raw["scene_id"]

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        assert "scene_id" in str(exc_info.value), (
            f"Expected 'scene_id' in error message, got: {exc_info.value}"
        )

    # -----------------------------------------------------------------------
    def test_missing_seed_raises(self):
        """Removing seed must raise ValidationError mentioning 'seed'."""
        raw = _minimal_raw()
        del raw["seed"]

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        assert "seed" in str(exc_info.value)

    # -----------------------------------------------------------------------
    def test_missing_room_raises(self):
        """Removing room must raise ValidationError mentioning 'room'."""
        raw = _minimal_raw()
        del raw["room"]

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        assert "room" in str(exc_info.value)

    # -----------------------------------------------------------------------
    def test_missing_sources_raises(self):
        """Removing sources must raise ValidationError mentioning 'sources'."""
        raw = _minimal_raw()
        del raw["sources"]

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        assert "sources" in str(exc_info.value)

    # -----------------------------------------------------------------------
    def test_empty_sources_raises(self):
        """An empty sources list must raise ValidationError."""
        raw = _minimal_raw()
        raw["sources"] = []

        with pytest.raises(ValidationError):
            self.validator.validate(raw)

    # -----------------------------------------------------------------------
    def test_missing_receivers_raises(self):
        """Removing receivers must raise ValidationError mentioning 'receivers'."""
        raw = _minimal_raw()
        del raw["receivers"]

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        assert "receivers" in str(exc_info.value)

    # -----------------------------------------------------------------------
    def test_invalid_sample_rate_raises(self):
        """sample_rate=12345 (not in VALID_SAMPLE_RATES) must raise ValidationError."""
        raw = _minimal_raw()
        raw["sample_rate"] = 12345

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        error_msg = str(exc_info.value)
        # Should mention sample_rate and/or the invalid value
        assert "sample_rate" in error_msg or "12345" in error_msg, (
            f"Expected 'sample_rate' or '12345' in error message, got: {error_msg}"
        )

    # -----------------------------------------------------------------------
    def test_valid_sample_rates_all_accepted(self):
        """All rates in VALID_SAMPLE_RATES must pass validation."""
        for rate in VALID_SAMPLE_RATES:
            raw = _minimal_raw()
            raw["sample_rate"] = rate
            cfg = self.validator.validate(raw)
            assert cfg.sample_rate == rate

    # -----------------------------------------------------------------------
    def test_invalid_ism_order_raises(self):
        """ism_order=11 (out of [1,10]) must raise ValidationError."""
        raw = _minimal_raw()
        raw["ism_order"] = 11

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        assert "ism_order" in str(exc_info.value)

    # -----------------------------------------------------------------------
    def test_ism_order_zero_raises(self):
        """ism_order=0 must raise ValidationError."""
        raw = _minimal_raw()
        raw["ism_order"] = 0

        with pytest.raises(ValidationError):
            self.validator.validate(raw)

    # -----------------------------------------------------------------------
    def test_ism_order_boundary_values(self):
        """ism_order=1 and ism_order=10 must both be accepted."""
        for order in (1, 10):
            raw = _minimal_raw()
            raw["ism_order"] = order
            cfg = self.validator.validate(raw)
            assert cfg.ism_order == order

    # -----------------------------------------------------------------------
    def test_schema_version_major_mismatch(self):
        """schema_version='2.0.0' vs expected '1.0.0' must raise ValidationError."""
        raw = _minimal_raw()
        raw["schema_version"] = "2.0.0"

        with pytest.raises(ValidationError) as exc_info:
            self.validator.validate(raw)

        error_msg = str(exc_info.value)
        assert "schema_version" in error_msg or "major" in error_msg.lower() or "2.0.0" in error_msg

    # -----------------------------------------------------------------------
    def test_schema_version_minor_mismatch_warns(self):
        """schema_version='1.1.0' should emit a UserWarning, not raise."""
        import warnings as _warnings

        raw = _minimal_raw()
        raw["schema_version"] = "1.1.0"

        with _warnings.catch_warnings(record=True) as w:
            _warnings.simplefilter("always")
            cfg = self.validator.validate(raw)

        assert isinstance(cfg, SceneConfig)
        # A warning should have been emitted
        assert any(issubclass(warning.category, UserWarning) for warning in w), (
            "Expected a UserWarning for minor version mismatch"
        )

    # -----------------------------------------------------------------------
    def test_schema_version_exact_match(self):
        """Exact schema_version match must return True from validate_schema_version."""
        result = self.validator.validate_schema_version(SCENE_CONFIG_SCHEMA_VERSION)
        assert result is True

    # -----------------------------------------------------------------------
    def test_source_missing_position_and_motion_raises(self):
        """A source without 'position' or 'motion' must raise ValidationError."""
        raw = _minimal_raw()
        raw["sources"] = [{"source_id": "s_bad"}]

        with pytest.raises(ValidationError):
            self.validator.validate(raw)

    # -----------------------------------------------------------------------
    def test_receiver_missing_position_and_motion_raises(self):
        """A receiver without 'position' or 'motion' must raise ValidationError."""
        raw = _minimal_raw()
        raw["receivers"] = [{"receiver_id": "r_bad"}]

        with pytest.raises(ValidationError):
            self.validator.validate(raw)

    # -----------------------------------------------------------------------
    def test_defaults_applied(self):
        """Optional fields should get correct defaults when absent."""
        raw = _minimal_raw()
        del raw["sample_rate"]
        del raw["ism_order"]

        cfg = self.validator.validate(raw)
        assert cfg.sample_rate == 16000
        assert cfg.ism_order == 3

    # -----------------------------------------------------------------------
    def test_motion_source_accepted(self):
        """A source with 'motion' instead of 'position' should be accepted."""
        raw = _minimal_raw()
        raw["sources"] = [
            {"source_id": "s_moving", "motion": {"type": "linear", "start": [1, 1, 1], "end": [4, 1, 1]}}
        ]
        cfg = self.validator.validate(raw)
        assert cfg.sources[0]["source_id"] == "s_moving"


# ---------------------------------------------------------------------------
# Seed derivation tests
# ---------------------------------------------------------------------------


class TestDeriveSubsystemSeeds:

    def test_derive_seeds_deterministic(self):
        """Same global_seed must always produce identical subsystem seeds."""
        seeds_a = derive_subsystem_seeds(42)
        seeds_b = derive_subsystem_seeds(42)
        assert seeds_a == seeds_b, "Seed derivation must be deterministic."

    # -----------------------------------------------------------------------
    def test_derive_seeds_unique(self):
        """All seven subsystem seeds must be different from each other."""
        seeds = derive_subsystem_seeds(42)
        values = list(seeds.values())
        assert len(values) == len(set(values)), (
            f"All subsystem seeds should be unique, got duplicates: {seeds}"
        )

    # -----------------------------------------------------------------------
    def test_derive_seeds_different_globals(self):
        """Different global seeds should produce different subsystem seeds."""
        seeds_0 = derive_subsystem_seeds(0)
        seeds_1 = derive_subsystem_seeds(1)
        assert seeds_0 != seeds_1

    # -----------------------------------------------------------------------
    def test_derive_seeds_non_negative(self):
        """All derived seeds must be non-negative 31-bit integers."""
        seeds = derive_subsystem_seeds(99999)
        for name, val in seeds.items():
            assert 0 <= val <= 0x7FFFFFFF, (
                f"Seed for '{name}' = {val} is out of 31-bit range."
            )

    # -----------------------------------------------------------------------
    def test_derive_seeds_canonical_names(self):
        """Default call should return all 7 canonical subsystem names."""
        seeds = derive_subsystem_seeds(1)
        expected_names = {
            "room", "material", "obstacle", "trajectory_src",
            "trajectory_rec", "noise", "codec",
        }
        assert set(seeds.keys()) == expected_names

    # -----------------------------------------------------------------------
    def test_derive_seeds_custom_names(self):
        """Custom subsystem names must produce one seed per name."""
        custom = ["alpha", "beta", "gamma"]
        seeds = derive_subsystem_seeds(7, subsystem_names=custom)
        assert set(seeds.keys()) == set(custom)
        assert len(seeds) == 3
