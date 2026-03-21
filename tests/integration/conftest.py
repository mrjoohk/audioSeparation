"""Pytest configuration for integration tests."""
import sys
from pathlib import Path

# Ensure src/ is on the path for all integration tests
sys.path.insert(0, str(Path(__file__).parents[2] / "src"))
