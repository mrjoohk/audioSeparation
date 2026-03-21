"""
Root conftest.py — ensures the src/ directory is on sys.path for all tests.
"""
import sys
import os

# Add src/ to path so that `import simulator` works without installing the package
_SRC = os.path.join(os.path.dirname(__file__), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
