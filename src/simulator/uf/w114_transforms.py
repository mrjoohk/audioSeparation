"""
W100000 Spatial Simulator — UF-W114 Coordinate Transforms
Implements UF-W114-01 through UF-W114-04.

UF-W114-01: define_world_frame
UF-W114-02: local_to_world
UF-W114-03: get_transform_at_tick
UF-W114-04: validate_transform_consistency

Coordinate convention
---------------------
All transforms use the **row-vector** convention:

    world_pos_h = local_pos_h @ T

where local_pos_h = [x, y, z, 1].

Consequently:
  - Translation is encoded in the last ROW of T: T[3, :3] = [tx, ty, tz].
  - The position of the origin under T is T[3, :3].

This is consistent with OpenGL / DirectX "row-major" matrix layout.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from simulator.types import (
    SourceTrajectory,
    Transform4x4,
    WorldFrame,
)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class TransformError(Exception):
    """Raised when a transform matrix is degenerate (determinant ≈ 0)."""


# ---------------------------------------------------------------------------
# UF-W114-01: define_world_frame
# ---------------------------------------------------------------------------

_SUPPORTED_CONVENTIONS = ("Y-up-RH", "Z-up-RH")


def define_world_frame(
    origin: Optional[np.ndarray] = None,
    convention: str = "Y-up-RH",
) -> WorldFrame:
    """
    Define the global world coordinate frame.

    Parameters
    ----------
    origin : array-like of shape (3,), optional
        World-space origin. Defaults to [0, 0, 0].
    convention : str
        Axis convention. Supported: "Y-up-RH", "Z-up-RH".

    Returns
    -------
    WorldFrame

    Raises
    ------
    ValueError
        If convention is not supported.
    """
    if convention not in _SUPPORTED_CONVENTIONS:
        raise ValueError(
            f"Unsupported convention '{convention}'. "
            f"Must be one of {_SUPPORTED_CONVENTIONS}."
        )

    if origin is None:
        origin_arr = np.zeros(3, dtype=np.float64)
    else:
        origin_arr = np.asarray(origin, dtype=np.float64).copy()
        if origin_arr.shape != (3,):
            raise ValueError(
                f"origin must have shape (3,); got {origin_arr.shape}."
            )

    return WorldFrame(origin=origin_arr, convention=convention, unit="meters")


# ---------------------------------------------------------------------------
# UF-W114-02: local_to_world
# ---------------------------------------------------------------------------

def local_to_world(
    local_pos: np.ndarray,
    transform: Transform4x4,
    world_frame: Optional[WorldFrame] = None,
) -> np.ndarray:
    """
    Transform a local 3-D position into world coordinates via a 4×4 matrix.

    Uses the **row-vector** convention:

        world_pos_h = [x, y, z, 1] @ T

    Translation is therefore encoded in T[3, :3].

    Parameters
    ----------
    local_pos : array-like of shape (3,)
        Position in local frame.
    transform : np.ndarray of shape (4, 4)
        Homogeneous transformation matrix (row-vector convention).
    world_frame : WorldFrame, optional
        Used for documentation/validation only; not applied as additional transform.

    Returns
    -------
    np.ndarray of shape (3,), dtype float64 — world position.

    Raises
    ------
    TransformError
        If the matrix shape is not (4, 4), or if |det(T)| < 1e-10.
    """
    T = np.asarray(transform, dtype=np.float64)
    if T.shape != (4, 4):
        raise TransformError(
            f"transform must be a 4×4 matrix; got shape {T.shape}."
        )

    det = np.linalg.det(T)
    if abs(det) < 1e-10:
        raise TransformError(
            f"Transform matrix is degenerate (det ≈ {det:.3e}); "
            "cannot reliably compute position."
        )

    pos = np.asarray(local_pos, dtype=np.float64)
    if pos.shape != (3,):
        raise TransformError(
            f"local_pos must have shape (3,); got {pos.shape}."
        )

    homogeneous = np.append(pos, 1.0)   # shape (4,)
    world_h = homogeneous @ T            # row-vector × matrix → shape (4,)
    return world_h[:3]


# ---------------------------------------------------------------------------
# UF-W114-03: get_transform_at_tick
# ---------------------------------------------------------------------------

def get_transform_at_tick(
    entity_id: str,
    tick_id: int,
    transform_sequence: Dict[str, List[Transform4x4]],
) -> Transform4x4:
    """
    Retrieve the 4×4 transform for an entity at a given tick.

    Parameters
    ----------
    entity_id : str
        Entity identifier.
    tick_id : int
        Desired tick index (0-based).
    transform_sequence : dict {entity_id → list of Transform4x4}
        Per-tick transform matrices for each entity.

    Returns
    -------
    Transform4x4 (np.ndarray of shape (4, 4))

    Behaviour
    ---------
    - Clamps tick_id to the last available tick if out-of-range.
    - Raises KeyError if entity_id is not in transform_sequence.
    """
    if entity_id not in transform_sequence:
        raise KeyError(
            f"Entity '{entity_id}' not found in transform_sequence. "
            f"Available entities: {list(transform_sequence.keys())}"
        )

    seq = transform_sequence[entity_id]
    if not seq:
        raise KeyError(
            f"Transform sequence for entity '{entity_id}' is empty."
        )

    clamped = min(tick_id, len(seq) - 1)
    return np.asarray(seq[clamped], dtype=np.float64)


# ---------------------------------------------------------------------------
# UF-W114-04: validate_transform_consistency
# ---------------------------------------------------------------------------

def validate_transform_consistency(
    transform_sequence: Dict[str, List[Transform4x4]],
    max_speed_m_per_s: float = 2.0,
    tick_rate_hz: float = 50.0,
) -> dict:
    """
    Check per-tick displacements for physically plausible motion.

    The maximum allowed displacement per tick is:
        threshold = max_speed_m_per_s / tick_rate_hz

    Translation is extracted from row 3 of each matrix (row-vector convention):
        position = T[3, :3]

    Parameters
    ----------
    transform_sequence : dict {entity_id → list of Transform4x4}
    max_speed_m_per_s : float
        Maximum allowable speed in m/s.
    tick_rate_hz : float
        Simulation tick rate in Hz.

    Returns
    -------
    dict with keys:
        "passed"     : bool — True if no violations found.
        "violations" : list of str — human-readable violation descriptions.
    """
    threshold_m = max_speed_m_per_s / tick_rate_hz
    violations: List[str] = []

    for entity_id, seq in transform_sequence.items():
        if len(seq) < 2:
            continue
        for tick in range(1, len(seq)):
            T_prev = np.asarray(seq[tick - 1], dtype=np.float64)
            T_curr = np.asarray(seq[tick], dtype=np.float64)
            # Extract translation from the last row (row-vector convention).
            # For a pure translation matrix built with make_translation_matrix,
            # T[3, :3] holds [tx, ty, tz].
            pos_prev = T_prev[3, :3]
            pos_curr = T_curr[3, :3]
            displacement = float(np.linalg.norm(pos_curr - pos_prev))
            if displacement > threshold_m:
                violations.append(
                    f"Entity '{entity_id}' tick {tick - 1}→{tick}: "
                    f"displacement {displacement:.4f} m exceeds threshold "
                    f"{threshold_m:.4f} m (speed {displacement * tick_rate_hz:.2f} m/s)."
                )

    return {
        "passed": len(violations) == 0,
        "violations": violations,
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def make_translation_matrix(tx: float, ty: float, tz: float) -> Transform4x4:
    """
    Build a 4×4 pure-translation matrix in **row-vector** convention.

    Layout:
        T[3, 0] = tx
        T[3, 1] = ty
        T[3, 2] = tz

    Such that:  [0, 0, 0, 1] @ T  ==  [tx, ty, tz, 1]
    """
    T = np.eye(4, dtype=np.float64)
    T[3, 0] = tx
    T[3, 1] = ty
    T[3, 2] = tz
    return T


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== UF-W114 smoke test ===")

    # 1. define_world_frame
    frame = define_world_frame(origin=[0.0, 0.0, 0.0], convention="Y-up-RH")
    print(f"WorldFrame: origin={frame.origin}, convention={frame.convention}")

    try:
        define_world_frame(convention="X-up")
    except ValueError as e:
        print(f"Expected ValueError: {e}")

    # 2. local_to_world — identity
    identity = np.eye(4, dtype=np.float64)
    pos = np.array([1.0, 2.0, 3.0])
    result = local_to_world(pos, identity)
    print(f"Identity transform: {result}")
    assert np.allclose(result, pos), f"Identity should preserve position: {result}"

    # 3. local_to_world — translation (row-vector convention)
    T_trans = make_translation_matrix(1.0, 2.0, 3.0)
    result_trans = local_to_world(np.array([0.0, 0.0, 0.0]), T_trans)
    print(f"Translation result: {result_trans}")
    assert np.allclose(result_trans, [1.0, 2.0, 3.0]), (
        f"Translation failed: {result_trans}"
    )

    # Translate non-zero origin
    result_nonzero = local_to_world(np.array([5.0, 0.0, 0.0]), T_trans)
    print(f"Non-zero origin translation: {result_nonzero}")
    assert np.allclose(result_nonzero, [6.0, 2.0, 3.0])

    # 4. get_transform_at_tick
    seq = {
        "src_0": [
            make_translation_matrix(0.0, 0.0, 0.0),
            make_translation_matrix(1.0, 0.0, 0.0),
        ],
    }
    T_at_0 = get_transform_at_tick("src_0", 0, seq)
    T_at_1 = get_transform_at_tick("src_0", 1, seq)
    T_clamp = get_transform_at_tick("src_0", 999, seq)  # should clamp to tick 1
    assert np.allclose(T_clamp, T_at_1), "Clamped tick should return last matrix"
    print(f"Clamped tick: T[3,0]={T_clamp[3,0]:.1f} (expected 1.0)")

    # 5. validate_transform_consistency
    # Normal motion (0.01 m/tick at 50 Hz = 0.5 m/s < 2.0 m/s)
    T0 = make_translation_matrix(0.00, 0.0, 0.0)
    T1 = make_translation_matrix(0.01, 0.0, 0.0)
    T2 = make_translation_matrix(0.02, 0.0, 0.0)
    result_ok = validate_transform_consistency({"walker": [T0, T1, T2]})
    print(f"Normal motion: passed={result_ok['passed']}")
    assert result_ok["passed"]

    # Teleportation (10 m/tick)
    T_tele = make_translation_matrix(10.0, 0.0, 0.0)
    result_bad = validate_transform_consistency({"teleporter": [T0, T_tele]})
    print(f"Teleportation: passed={result_bad['passed']}, violations={result_bad['violations']}")
    assert not result_bad["passed"]

    print("All smoke tests passed.")
