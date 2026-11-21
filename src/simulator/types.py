"""
W100000 Spatial Simulator — Shared Type Definitions
All dataclasses and type aliases used across UF/IF modules.

Coordinate convention: Right-hand Y-up, meters.
Audio: float32 NumPy arrays, channel-major ordering.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPEED_OF_SOUND: float = 343.0           # m/s at 20°C
OCTAVE_BAND_CENTERS: Tuple[float, ...] = (125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0)
VALID_SAMPLE_RATES: Tuple[int, ...] = (8000, 16000, 22050, 44100, 48000)
MIN_ROOM_VOLUME_M3: float = 10.0
MAX_ROOM_VOLUME_M3: float = 5000.0
MAX_SOURCES: int = 8
MAX_MIC_CHANNELS: int = 64
MAX_RIR_DURATION_S: float = 4.0
MIN_SOURCE_MIC_DIST_M: float = 0.1
MAX_SOURCE_MIC_DIST_M: float = 25.0
DEFAULT_DURATION_S: float = 5.0          # single scene-length default (render + trajectories)
DEFAULT_TICK_RATE_HZ: float = 50.0

# ---------------------------------------------------------------------------
# Room / Geometry Types
# ---------------------------------------------------------------------------

@dataclass
class Surface:
    """A single planar room surface."""
    surface_id: str
    normal: np.ndarray          # float[3], unit vector, world frame
    vertices: np.ndarray        # float[N×3], corner vertices in order
    area_m2: float


@dataclass
class RoomPrimitive:
    """Parametric room built from a named primitive type."""
    room_type: str              # "shoebox" | "corridor" | "hall"
    dimensions: Dict[str, float]  # e.g. {"L": 5.0, "W": 4.0, "H": 3.0}
    surfaces: List[Surface]
    surface_ids: List[str]

    @property
    def volume_m3(self) -> float:
        d = self.dimensions
        return d.get("L", 0.0) * d.get("W", 0.0) * d.get("H", 0.0)


@dataclass
class MeshRoom:
    """Triangle-mesh room geometry."""
    vertices: np.ndarray        # float[V×3]
    faces: np.ndarray           # int[F×3]
    surface_normals: np.ndarray # float[F×3]
    source_file: Optional[str] = None
    scale: float = 1.0


@dataclass
class AABB:
    """Axis-Aligned Bounding Box."""
    min_corner: np.ndarray      # float[3]
    max_corner: np.ndarray      # float[3]

    @property
    def volume_m3(self) -> float:
        d = self.max_corner - self.min_corner
        return float(d[0] * d[1] * d[2])

    @property
    def dimensions(self) -> np.ndarray:
        return self.max_corner - self.min_corner

    def contains(self, point: np.ndarray, margin: float = 0.0) -> bool:
        return bool(np.all(point >= self.min_corner + margin) and
                    np.all(point <= self.max_corner - margin))


RoomGeometry = Union[RoomPrimitive, MeshRoom]

# ---------------------------------------------------------------------------
# Material Types
# ---------------------------------------------------------------------------

@dataclass
class MaterialSpec:
    """Frequency-dependent acoustic absorption/scattering for one material."""
    name: str
    alpha: np.ndarray   # float[6], absorption coefficients per octave band, 0–1
    sigma: np.ndarray   # float[6], scattering coefficients per octave band, 0–1

    def __post_init__(self):
        self.alpha = np.asarray(self.alpha, dtype=np.float64)
        self.sigma = np.asarray(self.sigma, dtype=np.float64)
        assert self.alpha.shape == (6,), "alpha must have 6 octave-band values"
        assert self.sigma.shape == (6,), "sigma must have 6 octave-band values"


# MaterialMap: surface_id → MaterialSpec
MaterialMap = Dict[str, MaterialSpec]

# MaterialDB: name → MaterialSpec (singleton managed in w112_material.py)

# ---------------------------------------------------------------------------
# Obstacle / Object Types
# ---------------------------------------------------------------------------

AcousticRole = str  # "reflective" | "absorptive" | "occluding"


@dataclass
class ObjectSpec:
    """Template for an object to be placed in the scene."""
    object_type: str            # e.g. "chair", "table", "partition"
    size: np.ndarray            # float[3], bounding box dimensions (m)
    acoustic_role: AcousticRole = "reflective"
    position: Optional[np.ndarray] = None   # If set, bypass rejection sampling
    rotation_y: float = 0.0                 # Rotation around Y axis (rad)


@dataclass
class PlacedObject:
    """An obstacle placed in world coordinates."""
    object_id: str
    object_type: str
    position: np.ndarray        # float[3], world frame centroid (m)
    size: np.ndarray            # float[3], bounding box half-extents (m)
    rotation_y: float           # rad, rotation around Y axis
    acoustic_role: AcousticRole = "reflective"

    @property
    def aabb(self) -> AABB:
        half = self.size / 2.0
        return AABB(self.position - half, self.position + half)


ObstacleLayout = List[PlacedObject]

# ---------------------------------------------------------------------------
# Coordinate / Transform Types
# ---------------------------------------------------------------------------

@dataclass
class WorldFrame:
    """Definition of the global world coordinate frame."""
    origin: np.ndarray          # float[3]
    convention: str             # "Y-up-RH" | "Z-up-RH"
    unit: str = "meters"


# Transform4x4: 4×4 homogeneous transformation matrix (float64)
Transform4x4 = np.ndarray      # shape (4, 4)


@dataclass
class LocalFrame:
    """Local coordinate frame of an entity."""
    entity_id: str
    position: np.ndarray        # float[3], world position
    orientation: np.ndarray     # float[4], quaternion (x,y,z,w)


# ---------------------------------------------------------------------------
# Trajectory Types
# ---------------------------------------------------------------------------

@dataclass
class TickState:
    """State of an entity at a single simulation tick."""
    tick_id: int
    timestamp_s: float
    position: np.ndarray        # float[3], world frame (m)
    velocity: np.ndarray        # float[3], m/s
    orientation: float          # yaw angle, rad (for sources)
    orientation_quat: Optional[np.ndarray] = None  # float[4] for receivers


@dataclass
class SourceTrajectory:
    """Time-indexed trajectory for a single source."""
    source_id: str
    ticks: List[TickState]
    tick_rate_hz: float

    def at(self, tick_id: int) -> TickState:
        idx = min(tick_id, len(self.ticks) - 1)
        return self.ticks[idx]


@dataclass
class ReceiverTrajectory:
    """Time-indexed trajectory for a microphone/listener receiver."""
    receiver_id: str
    ticks: List[TickState]
    tick_rate_hz: float

    def at(self, tick_id: int) -> TickState:
        idx = min(tick_id, len(self.ticks) - 1)
        return self.ticks[idx]


# ---------------------------------------------------------------------------
# Scene State
# ---------------------------------------------------------------------------

@dataclass
class SourceState:
    """Runtime state of one audio source at a tick."""
    source_id: str
    position: np.ndarray        # float[3], world frame (m)
    velocity: np.ndarray        # float[3], m/s
    orientation: float          # yaw, rad
    active: bool = True


@dataclass
class ArrayConfig:
    """Microphone array geometry."""
    array_id: str
    topology: str               # "ULA" | "circular" | "custom"
    nominal_positions: np.ndarray  # float[N×3], relative to array center (m)
    effective_positions: Optional[np.ndarray] = None  # after perturbation
    clock_skew_samples: Optional[np.ndarray] = None   # int[N]


@dataclass
class ReceiverState:
    """Runtime state of one receiver at a tick."""
    receiver_id: str
    position: np.ndarray        # float[3], world frame (m)
    orientation_quat: np.ndarray  # float[4], quaternion (x,y,z,w)
    array_config: Optional[ArrayConfig] = None
    is_binaural: bool = False


@dataclass
class SceneState:
    """Complete scene state at one simulation tick."""
    tick_id: int
    room: RoomGeometry
    sources: List[SourceState]
    receivers: List[ReceiverState]
    materials: MaterialMap
    obstacles: ObstacleLayout


# ---------------------------------------------------------------------------
# Acoustic Computation Results
# ---------------------------------------------------------------------------

@dataclass
class DirectPath:
    """Direct-path propagation result for one source-receiver pair."""
    source_id: str
    receiver_id: str
    distance_m: float
    delay_s: float
    delay_samples: int
    attenuation_linear: float
    doa_az_rad: float           # azimuth in receiver frame
    doa_el_rad: float           # elevation in receiver frame
    air_atten_db: float = 0.0
    doppler_factor: float = 1.0


@dataclass
class ImageSource:
    """One image source from ISM."""
    position: np.ndarray        # float[3], world frame (m)
    reflection_order: int
    path_gain: float            # linear amplitude gain


@dataclass
class LateReverbSpec:
    """Parameters for stochastic late reverberation tail."""
    rt60_s: float
    mixing_time_ms: float
    seed: int


@dataclass
class ReflectionData:
    """Early reflection + late reverb description."""
    image_sources: List[ImageSource]
    late_tail_spec: LateReverbSpec


@dataclass
class OcclusionResult:
    """Occlusion/diffraction result for one source-receiver pair at one tick."""
    source_id: str
    receiver_id: str
    visible: bool
    blocking_object_id: Optional[str]
    loss_db: float              # total occlusion loss (frequency-independent)
    loss_db_per_band: np.ndarray  # float[6], per octave band


@dataclass
class RIR:
    """Room Impulse Response for one source-receiver pair."""
    source_id: str
    receiver_id: str
    h: np.ndarray               # float32[N_samples]
    fs: int
    rt60_measured_s: float
    drr_db: float
    peak_delay_samples: int


@dataclass
class BRIR:
    """Binaural Room Impulse Response (left + right ears)."""
    source_id: str
    receiver_id: str
    h: np.ndarray               # float32[2 × N_samples], left=0 right=1
    fs: int
    subject_id: int
    doa_az_deg: float
    doa_el_deg: float


# ---------------------------------------------------------------------------
# Device / Capture Types
# ---------------------------------------------------------------------------

@dataclass
class MicSpec:
    """Specification for one microphone channel."""
    mic_id: str
    freq_response_db: np.ndarray   # float[F], dB at freq_bins Hz
    freq_bins_hz: np.ndarray       # float[F]
    pattern_type: str              # "omni"|"cardioid"|"supercardioid"|"figure8"
    sensitivity_db: float = 0.0   # dB relative to nominal


@dataclass
class ImpairmentSpec:
    """Codec/channel impairment configuration."""
    impairment_type: str            # "bandwidth"|"codec"|"packet_loss"|"none"
    bandwidth_hz: Optional[float] = None     # for bandwidth limit
    packet_error_rate: Optional[float] = None  # PER ∈ [0, 0.2]
    segment_duration_ms: Optional[float] = None  # for packet loss


# ---------------------------------------------------------------------------
# Config / Job Types
# ---------------------------------------------------------------------------

@dataclass
class SceneConfig:
    """Top-level scene configuration (output of IF-W151)."""
    scene_id: str
    seed: int
    schema_version: str
    room: dict
    materials: dict
    sources: List[dict]
    receivers: List[dict]
    motion: Optional[dict] = None
    impairments: Optional[dict] = None
    output_dir: str = "output"
    sample_rate: int = 16000
    ism_order: int = 3
    speed_of_sound: float = SPEED_OF_SOUND
    extras: dict = field(default_factory=dict)  # render / qc / reference_receiver


@dataclass
class AcousticSummary:
    """Per-scene acoustic quality summary for metadata export."""
    scene_id: str
    rt60_measured_s: float
    drr_db: float
    snr_db: Optional[float]
    doa_az_deg: Optional[float]
    doa_el_deg: Optional[float]
    sabine_rt60_s: Optional[float] = None


@dataclass
class ExecutionSummary:
    """Batch execution result summary."""
    n_completed: int
    n_failed: int
    n_total: int
    elapsed_s: float
    throughput_scenes_per_hour: float
    failed_scene_ids: List[str] = field(default_factory=list)
    # --- resume / pilot metrics (design §4.5, F-08, F-11) ---
    n_skipped: int = 0                       # verified outputs reused from a previous run
    failure_reasons: Dict[str, str] = field(default_factory=dict)  # scene_id -> reason
    audio_seconds_completed: float = 0.0     # rendered audio (per channel) in this run
    bytes_written: int = 0
    qc_passed_audio_hours_per_hour: float = 0.0
    duplicate_groups: List[List[str]] = field(default_factory=list)  # same fingerprint


# ---------------------------------------------------------------------------
# Validation Results
# ---------------------------------------------------------------------------

@dataclass
class MeshValidationResult:
    """Result from UF-W111-03 manifold check."""
    is_valid: bool
    open_edges: int
    degenerate_faces: int


@dataclass
class PlausibilityReport:
    """Acoustic plausibility check result (UF-W155-01)."""
    passed: bool
    predicted_rt60_s: float
    predicted_drr_db: float
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
