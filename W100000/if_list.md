# W100000 Integration Function (IF) List
**Date:** 2026-03-21
**Hierarchy:** IC-W1-XX (Integrated Capability) → IF (W1X0000) → UF (UF-W1XX-0X)

---

## Hierarchy Map

```
W100000 Spatial Simulator
├── IC-W1-01. 3D Acoustic Scene Definition
│   ├── IF-W111: Room Geometry Modeling
│   ├── IF-W112: Surface/Material Property Modeling
│   ├── IF-W113: Object Placement & Obstacle Modeling
│   ├── IF-W114: Coordinate System & Transform Management
│   └── IF-W115: Scene State Manager  [NEW — see R-03]
│
├── IC-W1-02. Acoustic Propagation and Rendering
│   ├── IF-W121: Direct-Path Computation
│   ├── IF-W122: Reflection & Reverberation Computation
│   ├── IF-W123: Diffraction/Occlusion Approximation
│   └── IF-W124: RIR/BRIR Generation & Rendering
│
├── IC-W1-03. Dynamic Scene Evolution
│   ├── IF-W131: Source Trajectory Generation
│   ├── IF-W132: Microphone/Listener Trajectory Generation
│   ├── IF-W133: Time-Varying Geometry Synchronization
│   └── IF-W134: Dynamic Rendering Control
│
├── IC-W1-04. Sensor/Device Realism Modeling
│   ├── IF-W141: Microphone Response Modeling
│   ├── IF-W142: Array Geometry/Error Modeling
│   ├── IF-W143: Electronic Noise & Gain Modeling
│   └── IF-W144: Codec/Channel Impairment Modeling
│
└── IC-W1-05. Simulator Orchestration & Export
    ├── IF-W151: Job Configuration Schema
    ├── IF-W152: Batch Execution Control
    ├── IF-W153: Metadata Export
    ├── IF-W154: Validation & Debugging Tools
    └── IF-W155: Scene Validation Pipeline  [NEW — see R-02]
```

---

## IF Definitions

### IF-W111. Room Geometry Modeling
- **Inputs:** room_type (str), dimension_params (dict, m), mesh_file (path, optional)
- **Outputs:** RoomGeometry {surfaces: List[Surface], bounding_box: AABB, volume: float (m³)}
- **Constraints:** Closed manifold; volume 10–5000 m³
- **Linked REQs:** REQ-W01
- **Downstream IFs:** IF-W112 (assigns materials to surfaces), IF-W113 (places objects within bounds), IF-W114 (defines world frame)

### IF-W112. Surface/Material Property Modeling
- **Inputs:** surface_id (str), material_name (str), seed (int)
- **Outputs:** MaterialMap {surface_id → MaterialSpec{α[6], σ[6]}}
- **Constraints:** α ∈ [0,1] per band; 6 ISO octave bands minimum
- **Linked REQs:** REQ-W02
- **Downstream IFs:** IF-W122 (uses α for reverb shaping), IF-W155 (validates acoustic plausibility)

### IF-W113. Object Placement & Obstacle Modeling
- **Inputs:** RoomGeometry, object_list (List[ObjectSpec]), seed (int)
- **Outputs:** ObstacleLayout {objects: List[PlacedObject{position, size, type: reflective|absorptive|occluding}]}
- **Constraints:** No inter-object collision; min 0.3 m clearance from walls
- **Linked REQs:** REQ-W13
- **Downstream IFs:** IF-W123 (occlusion testing), IF-W115 (scene state)

### IF-W114. Coordinate System & Transform Management
- **Inputs:** entity_local_frames (List[LocalFrame]), tick_id (int)
- **Outputs:** WorldTransformGraph {entity_id → Transform4x4}
- **Constraints:** Right-hand coordinate system, Y-up convention, meters
- **Linked REQs:** REQ-W03
- **Downstream IFs:** All IFs consuming position/orientation data

### IF-W115. Scene State Manager  [NEW]
- **Inputs:** RoomGeometry, MaterialMap, ObstacleLayout, source_trajectories, receiver_trajectories, tick_id (int)
- **Outputs:** SceneState {tick_id, room, sources: List[SourceState], receivers: List[ReceiverState], materials, obstacles}
- **Constraints:** Must be serializable; tick_id must be monotonically increasing
- **Linked REQs:** REQ-W06, REQ-W09
- **Downstream IFs:** IF-W121, IF-W122, IF-W123, IF-W124, IF-W134

### IF-W121. Direct-Path Computation
- **Inputs:** SceneState (source + receiver positions), Fs (int, Hz)
- **Outputs:** DirectPath {delay_s: float, attenuation: float, doa_az_rad: float, doa_el_rad: float}
- **Constraints:** Distance ∈ [0.1, 25] m; delay quantized to 1/Fs
- **Linked REQs:** REQ-W03
- **Downstream IFs:** IF-W124 (direct component of RIR)

### IF-W122. Reflection & Reverberation Computation
- **Inputs:** SceneState, ISM_order (int, 1–10), Fs (int, Hz)
- **Outputs:** ReflectionData {image_sources: List[ImageSource{position, order, path_loss}], late_tail: LateReverbSpec}
- **Constraints:** ISM for shoebox; ray tracing for mesh; energy < −60 dB at RIR end
- **Linked REQs:** REQ-W04
- **Downstream IFs:** IF-W124

### IF-W123. Diffraction/Occlusion Approximation
- **Inputs:** SceneState (source, receiver, obstacles), frequency_bands (List[float, Hz])
- **Outputs:** OcclusionResult {visibility: bool, loss_db_per_band: float[6]}
- **Constraints:** Maekawa model; loss ∈ [0, 20] dB
- **Linked REQs:** REQ-W13
- **Downstream IFs:** IF-W124

### IF-W124. RIR/BRIR Generation & Rendering
- **Inputs:** DirectPath, ReflectionData, OcclusionResult, HRTFConfig (optional), Fs (int, Hz)
- **Outputs:** RIR {h: ndarray[N_samples, float32], rt60_measured: float, drr_db: float}; or BRIR {h: ndarray[2×N_samples]}
- **Constraints:** Duration ≤ 4.0 s; throughput ≥ 1000 RIRs/s at Fs=16kHz ISM-3
- **Linked REQs:** REQ-W04, REQ-W05
- **Downstream IFs:** IF-W134 (convolution rendering)

### IF-W131. Source Trajectory Generation
- **Inputs:** motion_type (str), RoomGeometry, duration_s (float), Fs_traj (int, Hz), seed (int)
- **Outputs:** SourceTrajectory {ticks: List[TickState{position[3], velocity[3], orientation}]}
- **Constraints:** All positions inside room; speed ≤ 2.0 m/s; min wall distance 0.5 m
- **Linked REQs:** REQ-W14
- **Downstream IFs:** IF-W115, IF-W133

### IF-W132. Microphone/Listener Trajectory Generation
- **Inputs:** receiver_type (str), RoomGeometry, duration_s (float), seed (int)
- **Outputs:** ReceiverTrajectory {ticks: List[TickState{position[3], orientation_quat[4]}]}
- **Constraints:** Same spatial constraints as IF-W131; orientation quaternion normalized
- **Linked REQs:** REQ-W14
- **Downstream IFs:** IF-W115, IF-W133

### IF-W133. Time-Varying Geometry Synchronization
- **Inputs:** SourceTrajectory, ReceiverTrajectory, static_scene (RoomGeometry, ObstacleLayout), tick_rate_hz (float)
- **Outputs:** SceneState sequence, temporal alignment log
- **Constraints:** All entities time-aligned to same tick grid; event timing (speech start/stop) synchronized
- **Linked REQs:** REQ-W06
- **Downstream IFs:** IF-W115, IF-W134

### IF-W134. Dynamic Rendering Control
- **Inputs:** SceneState sequence, segment_length_ms (float), re_render_threshold_m (float)
- **Outputs:** Rendered multichannel waveform (ndarray[C×N_samples, float32])
- **Constraints:** Crossfade between segments; click energy < −60 dB at boundaries
- **Linked REQs:** REQ-W06
- **Downstream IFs:** IF-W141 (microphone response applied post-render)

### IF-W141. Microphone Response Modeling
- **Inputs:** clean_signal (ndarray[C×N, float32]), mic_config (List[MicSpec{freq_response, pattern, sensitivity}])
- **Outputs:** mic_filtered_signal (ndarray[C×N, float32])
- **Constraints:** Per-channel FIR filter; directional pickup applied via per-angle gain lookup
- **Linked REQs:** REQ-W08
- **Downstream IFs:** IF-W142

### IF-W142. Array Geometry/Error Modeling
- **Inputs:** array_template (str), nominal_positions (N×3, float, m), perturbation_sigma_m (float), seed (int)
- **Outputs:** EffectiveArrayGeometry {positions: N×3 float, clock_skew_samples: N int}
- **Constraints:** σ ≤ 5 mm; clock skew ≤ 1 sample
- **Linked REQs:** REQ-W07
- **Downstream IFs:** IF-W143

### IF-W143. Electronic Noise & Gain Modeling
- **Inputs:** mic_filtered_signal (ndarray[C×N, float32]), noise_floor_dbfs (float), gain_db (float), clip_threshold_dbfs (float), seed (int)
- **Outputs:** degraded_signal (ndarray[C×N, float32]), snr_per_channel (float[C])
- **Constraints:** Noise floor −70 to −30 dBFS; clipping at threshold
- **Linked REQs:** REQ-W08
- **Downstream IFs:** IF-W144

### IF-W144. Codec/Channel Impairment Modeling
- **Inputs:** degraded_signal (ndarray[C×N, float32]), impairment_config (ImpairmentSpec), Fs (int, Hz)
- **Outputs:** impaired_signal (ndarray[C×N, float32]), impairment_tags (dict)
- **Constraints:** Bandwidth filter order ≤ 256; PER ∈ [0, 0.2]
- **Linked REQs:** REQ-W15
- **Downstream IFs:** IF-W153 (tags written to metadata)

### IF-W151. Job Configuration Schema
- **Inputs:** raw_config (dict), schema_version (str)
- **Outputs:** SceneConfig (validated, typed dataclass), ValidationReport
- **Constraints:** Validation < 10 ms; MAJOR version mismatch raises error
- **Linked REQs:** REQ-W09
- **Downstream IFs:** All IFs (SceneConfig is the root parameter object)

### IF-W152. Batch Execution Control
- **Inputs:** job_queue (List[SceneConfig]), worker_count (int), output_dir (str), checkpoint_file (path)
- **Outputs:** Execution summary {n_completed, n_failed, elapsed_s, throughput_scenes_per_hour}
- **Constraints:** ≥ 1000 scenes/hour on 8-core CPU; worker memory ≤ 4 GB; checkpoint enables resume
- **Linked REQs:** REQ-W10
- **Downstream IFs:** IF-W153 (collects manifests per job)

### IF-W153. Metadata Export
- **Inputs:** rendered_scene_dir (str), SceneConfig, acoustic_summary (AcousticSummary)
- **Outputs:** scene_manifest.json, dataset_index.json entry
- **Constraints:** Schema v1.0; all file paths relative to output_dir
- **Linked REQs:** REQ-W11
- **Downstream IFs:** None (terminal output)

### IF-W154. Validation & Debugging Tools
- **Inputs:** SceneState or rendered_scene_dir
- **Outputs:** Visualization PNGs (room_layout, rir_plot, waveform_plot, rt60_bar)
- **Constraints:** Headless matplotlib; < 5 s per scene
- **Linked REQs:** REQ-W12
- **Downstream IFs:** None (diagnostic output)

### IF-W155. Scene Validation Pipeline  [NEW]
- **Inputs:** RoomGeometry, MaterialMap, SceneConfig
- **Outputs:** ValidationResult {passed: bool, warnings: List[str], errors: List[str]}
- **Constraints:** Must run before any rendering; acoustic plausibility checks (RT60 bounds, DRR range)
- **Linked REQs:** REQ-W01, REQ-W02, REQ-W04
- **Downstream IFs:** IF-W122 (blocked if validation fails)
