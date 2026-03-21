"""
UF-W123: Occlusion and Diffraction
Implements UF-W123-01 through UF-W123-04.

Functions:
    visibility_test              (UF-W123-01)
    estimate_occlusion_loss      (UF-W123-02)
    maekawa_diffraction          (UF-W123-03)
    update_occlusion_if_moved    (UF-W123-04)
    compute_full_occlusion       (helper)
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Path / type imports
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parents[3] / "src"))
from simulator.types import (
    OCTAVE_BAND_CENTERS,
    SPEED_OF_SOUND,
    AABB,
    OcclusionResult,
    PlacedObject,
    ObstacleLayout,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_OCCLUSION_DB: float = 20.0   # dB cap for occlusion loss


# ---------------------------------------------------------------------------
# UF-W123-01  Ray-AABB Visibility Test
# ---------------------------------------------------------------------------

def _ray_aabb_intersect(
    origin: np.ndarray,
    direction: np.ndarray,
    t_max: float,
    aabb: AABB,
) -> bool:
    """Parametric ray-AABB intersection test.

    Tests whether the segment P(t) = origin + t * direction for t ∈ [0, t_max]
    intersects the axis-aligned bounding box.

    Parameters
    ----------
    origin    : (3,) array   ray start point
    direction : (3,) array   (unnormalised) ray direction vector
    t_max     : float        maximum t value (= 1 for a segment)
    aabb      : AABB

    Returns
    -------
    bool  True if the ray segment intersects the AABB
    """
    t_min_all = 0.0
    t_max_all = t_max

    for i in range(3):
        d = direction[i]
        if abs(d) < 1e-12:
            # Ray is parallel to slab; check if origin is inside slab
            if origin[i] < aabb.min_corner[i] or origin[i] > aabb.max_corner[i]:
                return False
        else:
            t1 = (aabb.min_corner[i] - origin[i]) / d
            t2 = (aabb.max_corner[i] - origin[i]) / d
            t_near = min(t1, t2)
            t_far  = max(t1, t2)
            t_min_all = max(t_min_all, t_near)
            t_max_all = min(t_max_all, t_far)
            if t_min_all > t_max_all:
                return False

    return t_min_all <= t_max_all


def visibility_test(
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    obstacles: ObstacleLayout,
) -> dict:
    """Test line-of-sight visibility using ray-AABB segment intersection.

    Parameters
    ----------
    src_pos   : array_like (3,)   source world position (m)
    mic_pos   : array_like (3,)   microphone world position (m)
    obstacles : ObstacleLayout    list of PlacedObject

    Returns
    -------
    dict with keys:
        "visible"            – bool
        "blocking_object_id" – str or None
    """
    src_pos = np.asarray(src_pos, dtype=np.float64)
    mic_pos = np.asarray(mic_pos, dtype=np.float64)

    direction = mic_pos - src_pos  # parametric direction; t=0 at src, t=1 at mic

    for obj in obstacles:
        aabb = obj.aabb
        if _ray_aabb_intersect(src_pos, direction, t_max=1.0, aabb=aabb):
            return {"visible": False, "blocking_object_id": str(obj.object_id)}

    return {"visible": True, "blocking_object_id": None}


# ---------------------------------------------------------------------------
# UF-W123-02  Occlusion Loss Estimation
# ---------------------------------------------------------------------------

def estimate_occlusion_loss(
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    obstacle: PlacedObject,
) -> float:
    """Estimate geometric occlusion loss in dB.

    The shadow fraction is computed by projecting the obstacle's bounding
    box onto the plane perpendicular to the source-microphone ray passing
    through the obstacle centre.  The fraction of the projected obstacle
    area relative to the maximum possible "blocking" area determines the
    occlusion loss.

    Loss mapping: 0 % occluded → 0 dB; 100 % → 20 dB (linear in fraction).

    Parameters
    ----------
    src_pos  : array_like (3,)   source position (m)
    mic_pos  : array_like (3,)   microphone position (m)
    obstacle : PlacedObject

    Returns
    -------
    float   loss_db ∈ [0, 20]
    """
    src_pos  = np.asarray(src_pos,  dtype=np.float64)
    mic_pos  = np.asarray(mic_pos,  dtype=np.float64)

    ray = mic_pos - src_pos
    ray_len = float(np.linalg.norm(ray))
    if ray_len < 1e-9:
        return 0.0

    ray_unit = ray / ray_len

    # Obstacle half-sizes
    half_size = np.asarray(obstacle.size, dtype=np.float64) / 2.0

    # Project half-sizes onto the perpendicular plane of the ray.
    # The "shadow" of the box in the direction of the ray depends on
    # which two dimensions are perpendicular to the ray.
    #
    # For each axis of the box, the projected extent onto the plane
    # perpendicular to ray_unit is:
    #     extent_i_in_plane = half_size[i] * sqrt(1 - dot(axis_i, ray_unit)^2)
    #
    # We use the standard basis vectors as box axes (AABB, no rotation applied
    # for this simplified model).
    axes = np.eye(3, dtype=np.float64)
    proj_extents = np.array([
        half_size[i] * math.sqrt(max(0.0, 1.0 - float(np.dot(axes[i], ray_unit)) ** 2))
        for i in range(3)
    ])

    # Projected shadow area ≈ product of the two largest perpendicular extents
    # (bounding rectangle of the shadow)
    sorted_extents = np.sort(proj_extents)  # ascending
    shadow_area = float(sorted_extents[1] * sorted_extents[2]) * 4.0  # full extents (2× half)

    # Reference area: the direct-path Fresnel zone area at the obstacle distance
    # For simplicity: reference area = max cross-section of obstacle bounding box
    face_areas = np.array([
        half_size[1] * half_size[2],
        half_size[0] * half_size[2],
        half_size[0] * half_size[1],
    ]) * 4.0  # convert from half to full

    ref_area = float(np.max(face_areas))
    if ref_area < 1e-12:
        return 0.0

    fraction = min(shadow_area / ref_area, 1.0)
    loss_db = fraction * _MAX_OCCLUSION_DB

    return float(np.clip(loss_db, 0.0, _MAX_OCCLUSION_DB))


# ---------------------------------------------------------------------------
# UF-W123-03  Maekawa Diffraction
# ---------------------------------------------------------------------------

def maekawa_diffraction(
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    edge_pos: np.ndarray,
    freq_hz: float,
    c: float = SPEED_OF_SOUND,
) -> float:
    """Compute diffraction gain via the Maekawa model.

    Parameters
    ----------
    src_pos  : array_like (3,)   source position (m)
    mic_pos  : array_like (3,)   microphone position (m)
    edge_pos : array_like (3,)   diffraction edge position (m)
    freq_hz  : float             frequency (Hz), must be > 0
    c        : float             speed of sound (m/s)

    Returns
    -------
    float   diffraction_gain_db ≤ 0

    Raises
    ------
    ValueError   if freq_hz <= 0
    """
    if freq_hz <= 0.0:
        raise ValueError(f"freq_hz must be positive; got {freq_hz}.")

    src_pos  = np.asarray(src_pos,  dtype=np.float64)
    mic_pos  = np.asarray(mic_pos,  dtype=np.float64)
    edge_pos = np.asarray(edge_pos, dtype=np.float64)

    d1 = float(np.linalg.norm(src_pos  - edge_pos))
    d2 = float(np.linalg.norm(mic_pos  - edge_pos))
    d  = float(np.linalg.norm(src_pos  - mic_pos))

    delta = d1 + d2 - d  # path length difference

    wavelength = c / float(freq_hz)
    N = 2.0 * delta / wavelength  # Fresnel number

    if N > 0.0:
        gain_db = -10.0 * math.log10(3.0 + 20.0 * N)
    else:
        gain_db = 0.0

    return float(gain_db)


# ---------------------------------------------------------------------------
# UF-W123-04  Cached Occlusion Update
# ---------------------------------------------------------------------------

def update_occlusion_if_moved(
    prev_result: OcclusionResult,
    prev_src_pos: np.ndarray,
    prev_mic_pos: np.ndarray,
    curr_src_pos: np.ndarray,
    curr_mic_pos: np.ndarray,
    obstacles: ObstacleLayout,
    threshold_m: float = 0.1,
    freq_bands: Optional[np.ndarray] = None,
) -> Tuple[OcclusionResult, bool]:
    """Return cached occlusion result if neither source nor mic moved much.

    If the maximum displacement of source or microphone exceeds
    ``threshold_m``, re-evaluate by calling ``compute_full_occlusion``.

    Parameters
    ----------
    prev_result   : OcclusionResult   previously computed result
    prev_src_pos  : array_like (3,)   previous source position
    prev_mic_pos  : array_like (3,)   previous mic position
    curr_src_pos  : array_like (3,)   current source position
    curr_mic_pos  : array_like (3,)   current mic position
    obstacles     : ObstacleLayout
    threshold_m   : float             distance threshold (m); default 0.1
    freq_bands    : array_like or None  frequencies for per-band computation

    Returns
    -------
    (OcclusionResult, updated: bool)
        updated=False if cached result returned, True if recomputed.
    """
    prev_src_pos = np.asarray(prev_src_pos, dtype=np.float64)
    prev_mic_pos = np.asarray(prev_mic_pos, dtype=np.float64)
    curr_src_pos = np.asarray(curr_src_pos, dtype=np.float64)
    curr_mic_pos = np.asarray(curr_mic_pos, dtype=np.float64)

    src_disp = float(np.linalg.norm(curr_src_pos - prev_src_pos))
    mic_disp = float(np.linalg.norm(curr_mic_pos - prev_mic_pos))
    max_disp = max(src_disp, mic_disp)

    if max_disp <= threshold_m:
        return prev_result, False

    new_result = compute_full_occlusion(
        src_id=prev_result.source_id,
        rec_id=prev_result.receiver_id,
        src_pos=curr_src_pos,
        mic_pos=curr_mic_pos,
        obstacles=obstacles,
        freq_bands=freq_bands,
    )
    return new_result, True


# ---------------------------------------------------------------------------
# Helper: compute_full_occlusion
# ---------------------------------------------------------------------------

def compute_full_occlusion(
    src_id: str,
    rec_id: str,
    src_pos: np.ndarray,
    mic_pos: np.ndarray,
    obstacles: ObstacleLayout,
    freq_bands: Optional[np.ndarray] = None,
) -> OcclusionResult:
    """Combine visibility, occlusion loss, and Maekawa diffraction.

    For each octave band the same geometric occlusion loss is applied
    (frequency-independent model), and Maekawa diffraction is computed at
    the band centre frequency for each blocking obstacle edge (approximated
    as the obstacle centroid).  The per-band loss is the sum of
    occlusion_loss and diffraction_gain (diffraction reduces the total loss).

    Parameters
    ----------
    src_id    : str
    rec_id    : str
    src_pos   : array_like (3,)
    mic_pos   : array_like (3,)
    obstacles : ObstacleLayout
    freq_bands : array_like (6,) or None
        Frequencies in Hz for per-band computation.
        Defaults to OCTAVE_BAND_CENTERS.

    Returns
    -------
    OcclusionResult
    """
    src_pos = np.asarray(src_pos, dtype=np.float64)
    mic_pos = np.asarray(mic_pos, dtype=np.float64)

    if freq_bands is None:
        freq_bands = np.array(OCTAVE_BAND_CENTERS, dtype=np.float64)
    else:
        freq_bands = np.asarray(freq_bands, dtype=np.float64)

    vis = visibility_test(src_pos, mic_pos, obstacles)
    visible = bool(vis["visible"])
    blocking_id = vis["blocking_object_id"]

    total_loss_db = 0.0
    loss_db_per_band = np.zeros(6, dtype=np.float64)

    if not visible:
        # Find the blocking obstacle and accumulate losses
        for obj in obstacles:
            aabb = obj.aabb
            direction = mic_pos - src_pos
            if not _ray_aabb_intersect(src_pos, direction, t_max=1.0, aabb=aabb):
                continue

            occ_loss = estimate_occlusion_loss(src_pos, mic_pos, obj)

            # Per-band: occlusion loss + Maekawa diffraction gain at each band
            edge_pos = np.asarray(obj.position, dtype=np.float64)
            for bi, fhz in enumerate(freq_bands):
                diff_gain = maekawa_diffraction(src_pos, mic_pos, edge_pos, float(fhz))
                # Occlusion loss minus diffraction relief (diffraction gain is ≤ 0)
                band_loss = max(0.0, occ_loss + diff_gain)  # diff_gain is negative
                loss_db_per_band[bi] += band_loss

        # total loss = mean across bands (or simple occ_loss for single blocker)
        total_loss_db = float(np.mean(loss_db_per_band))

    return OcclusionResult(
        source_id=src_id,
        receiver_id=rec_id,
        visible=visible,
        blocking_object_id=blocking_id,
        loss_db=float(total_loss_db),
        loss_db_per_band=loss_db_per_band.astype(np.float64),
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import numpy as np

    src = np.array([0.0, 1.0, 0.0])
    mic = np.array([5.0, 1.0, 0.0])

    # No obstacles
    result = visibility_test(src, mic, [])
    print(f"[smoke] visibility (no obstacles): {result}")

    # Place an obstacle between src and mic
    wall = PlacedObject(
        object_id="wall_01",
        object_type="partition",
        position=np.array([2.5, 1.0, 0.0]),
        size=np.array([0.2, 2.0, 2.0]),
        rotation_y=0.0,
        acoustic_role="occluding",
    )
    result2 = visibility_test(src, mic, [wall])
    print(f"[smoke] visibility (wall blocking): {result2}")

    # Maekawa
    edge = np.array([2.5, 2.0, 0.0])
    diff_gain = maekawa_diffraction(src, mic, edge, freq_hz=1000.0)
    print(f"[smoke] Maekawa diffraction @1 kHz: {diff_gain:.2f} dB")

    # compute_full_occlusion
    occ = compute_full_occlusion("src0", "mic0", src, mic, [wall])
    print(f"[smoke] Full occlusion: visible={occ.visible}, loss={occ.loss_db:.2f} dB")

    # update_occlusion_if_moved — sub-threshold
    curr_src = src + np.array([0.05, 0.0, 0.0])
    cached_occ, updated = update_occlusion_if_moved(occ, src, mic, curr_src, mic, [wall])
    print(f"[smoke] update_occlusion (sub-threshold): updated={updated}")

    print("[smoke] w123_occlusion OK")
