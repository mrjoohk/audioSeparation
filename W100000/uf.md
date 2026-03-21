# W100000 Unit Function (UF) Blocks
**Date:** 2026-03-21
**Note:** Original 44 UFs retained; I/O contracts, algorithm summaries, and edge cases added.
New UFs (marked [NEW]) added for gaps identified in design analysis.

---

## IF-W111: Room Geometry Modeling

### UF-W111-01. Define room primitive
- **UF-ID:** UF-W111-01
- **Parent IF:** IF-W111
- **Goal:** Instantiate a parametric room from a named primitive type and dimension parameters.
- **I/O Contract:**
  - Input: `room_type`: str ∈ {"shoebox","corridor","hall"}; `params`: dict (e.g., {L:float, W:float, H:float}, meters)
  - Output: `RoomPrimitive`: dataclass {type, dimensions: dict, surface_ids: List[str]}
- **Algorithm Summary:** Construct axis-aligned surface list from dimension params. For shoebox: 6 rectangular panels.
- **Edge Cases:** H < 1.5 m (unusable headroom) → warning; any dimension < 0.5 m → error
- **Verification Plan:** `pytest test_room_geometry.py::test_shoebox_dimensions`; assert surface count = 6 for shoebox
- **Evidence Pack Fields:** scenario_id, room_type, dimensions, surface_count

### UF-W111-02. Import CAD/mesh geometry
- **UF-ID:** UF-W111-02
- **Parent IF:** IF-W111
- **Goal:** Load a watertight triangle mesh from file and convert to room surface representation.
- **I/O Contract:**
  - Input: `mesh_file`: path (OBJ/PLY/STL); `scale`: float (m/unit, default 1.0)
  - Output: `MeshRoom`: dataclass {vertices: float[V×3], faces: int[F×3], surface_normals: float[F×3]}
- **Algorithm Summary:** Load with trimesh; apply scale; compute face normals. Validate closed manifold.
- **Edge Cases:** Non-manifold mesh → raise MeshError; empty file → raise IOError; non-triangulated → auto-triangulate with warning
- **Verification Plan:** `pytest test_room_geometry.py::test_mesh_import`; test with valid OBJ and invalid mesh
- **Evidence Pack Fields:** mesh_file, vertex_count, face_count, is_watertight

### UF-W111-03. Validate manifold/closure
- **UF-ID:** UF-W111-03
- **Parent IF:** IF-W111
- **Goal:** Verify the room mesh is watertight (all edges shared by exactly 2 faces, no boundary edges).
- **I/O Contract:**
  - Input: `mesh`: MeshRoom
  - Output: `ValidationResult`: {is_valid: bool, open_edges: int, degenerate_faces: int}
- **Algorithm Summary:** Check edge manifold condition via half-edge analysis; detect degenerate faces (area < 1e-6 m²).
- **Edge Cases:** Zero-area faces → degenerate_faces count; holes in mesh → open_edges > 0 → is_valid=False
- **Verification Plan:** `pytest test_room_geometry.py::test_manifold_validation`
- **Evidence Pack Fields:** is_valid, open_edges, degenerate_faces

### UF-W111-04. Generate bounding volume
- **UF-ID:** UF-W111-04
- **Parent IF:** IF-W111
- **Goal:** Compute axis-aligned bounding box (AABB) and approximate volume for the room.
- **I/O Contract:**
  - Input: `room`: RoomPrimitive or MeshRoom
  - Output: `AABB`: {min_corner: float[3], max_corner: float[3], volume: float (m³)}
- **Algorithm Summary:** min/max over all vertices. Volume = analytical for primitive, mesh volume via divergence theorem for mesh.
- **Edge Cases:** Volume < 10 m³ → warning; volume > 5000 m³ → warning
- **Verification Plan:** `pytest test_room_geometry.py::test_bounding_volume`; shoebox 5×4×3 → volume=60.0±0.001 m³
- **Evidence Pack Fields:** volume_m3, bbox_dimensions

---

## IF-W112: Surface/Material Property Modeling

### UF-W112-01. Register material class
- **UF-ID:** UF-W112-01
- **Parent IF:** IF-W112
- **Goal:** Add a named material with default absorption/scattering coefficients to the global material database.
- **I/O Contract:**
  - Input: `name`: str; `alpha`: float[6] (0–1, 125–4000 Hz octave bands); `sigma`: float[6] (0–1)
  - Output: `MaterialSpec`: dataclass {name, alpha[6], sigma[6]}; registered in MaterialDB singleton
- **Algorithm Summary:** Validate ranges; store in dict keyed by name.
- **Edge Cases:** Duplicate name → overwrite with warning; any α > 1 → clamp and warn; name="" → error
- **Verification Plan:** `pytest test_material_db.py::test_register`
- **Evidence Pack Fields:** material_name, alpha_bands, sigma_bands

### UF-W112-02. Assign frequency-dependent coefficients
- **UF-ID:** UF-W112-02
- **Parent IF:** IF-W112
- **Goal:** Map material names to room surfaces, producing a complete MaterialMap for the scene.
- **I/O Contract:**
  - Input: `surface_ids`: List[str]; `material_assignments`: dict {surface_id → material_name}; `MaterialDB`
  - Output: `MaterialMap`: dict {surface_id → MaterialSpec}
- **Algorithm Summary:** Lookup each surface_id in material_assignments; fetch MaterialSpec from MaterialDB.
- **Edge Cases:** Unknown surface_id → KeyError; unknown material_name → use default material + warning
- **Verification Plan:** `pytest test_material_db.py::test_assign`
- **Evidence Pack Fields:** scene_id, surface_count, unique_materials

### UF-W112-03. Stochastic material variation
- **UF-ID:** UF-W112-03
- **Parent IF:** IF-W112
- **Goal:** Apply seed-controlled random perturbation to absorption coefficients for dataset diversity.
- **I/O Contract:**
  - Input: `base_spec`: MaterialSpec; `variation_sigma`: float (default 0.05); `seed`: int
  - Output: `PerturbedMaterialSpec`: MaterialSpec with α_i ∈ [max(0, α_i−3σ), min(1, α_i+3σ)]
- **Algorithm Summary:** Seeded numpy.random.default_rng; sample Gaussian perturbation per band; clip to [0,1].
- **Edge Cases:** σ=0 → return base_spec unchanged; seed=None → raise error (reproducibility required)
- **Verification Plan:** `pytest test_material_db.py::test_stochastic_variation`; same seed → same output
- **Evidence Pack Fields:** seed, variation_sigma, alpha_before, alpha_after

### UF-W112-04. Export material map
- **UF-ID:** UF-W112-04
- **Parent IF:** IF-W112
- **Goal:** Serialize the scene's MaterialMap to JSON for logging and reproducibility.
- **I/O Contract:**
  - Input: `material_map`: MaterialMap; `output_path`: str
  - Output: JSON file at output_path; returns dict (echo)
- **Algorithm Summary:** Convert MaterialMap to nested dict; json.dump with indent=2.
- **Edge Cases:** output_path parent dir not exist → create; write permission denied → raise IOError
- **Verification Plan:** `pytest test_material_db.py::test_export`
- **Evidence Pack Fields:** output_path, n_surfaces

---

## IF-W113: Object Placement & Obstacle Modeling

### UF-W113-01. Place obstacle objects
- **UF-ID:** UF-W113-01
- **Parent IF:** IF-W113
- **Goal:** Position furniture/partition/obstacle objects in the room with collision-aware placement.
- **I/O Contract:**
  - Input: `room_bbox`: AABB; `object_specs`: List[ObjectSpec{type, size[3], object_type}]; `seed`: int
  - Output: `ObstacleLayout`: List[PlacedObject{id, position[3], size[3], rotation_y, object_type}]
- **Algorithm Summary:** Seeded rejection sampling; place each object; check overlap with existing + walls; max 100 attempts per object.
- **Edge Cases:** Room too small to fit all objects → place as many as possible + warning; size > room dimension → error
- **Verification Plan:** `pytest test_obstacle.py::test_placement_no_collision`
- **Evidence Pack Fields:** n_placed, n_rejected, scene_id

### UF-W113-02. Tag object acoustic role
- **UF-ID:** UF-W113-02
- **Parent IF:** IF-W113
- **Goal:** Assign acoustic role (reflective, absorptive, occluding) to each placed object.
- **I/O Contract:**
  - Input: `placed_objects`: List[PlacedObject]; `role_map`: dict {object_type → AcousticRole}
  - Output: `AnnotatedObstacleLayout`: same as PlacedObject + {acoustic_role: str}
- **Algorithm Summary:** Lookup object_type in role_map; assign AcousticRole.
- **Edge Cases:** Unknown object_type → assign 'reflective' as default + warning
- **Verification Plan:** `pytest test_obstacle.py::test_role_assignment`
- **Evidence Pack Fields:** role_distribution dict

### UF-W113-03. Enforce collision-aware constraints
- **UF-ID:** UF-W113-03
- **Parent IF:** IF-W113
- **Goal:** Validate that no two objects and no object-wall pairs overlap beyond clearance threshold.
- **I/O Contract:**
  - Input: `layout`: ObstacleLayout; `room_bbox`: AABB; `min_clearance_m`: float (default 0.3)
  - Output: `CollisionReport`: {n_violations: int, violating_pairs: List[Tuple[str,str]]}
- **Algorithm Summary:** AABB pair-wise overlap test with clearance margin; check wall proximity.
- **Edge Cases:** Single object → no pair to check; clearance=0 → allow touching
- **Verification Plan:** `pytest test_obstacle.py::test_collision_check`
- **Evidence Pack Fields:** n_violations, violating_pairs

### UF-W113-04. Serialize object layout
- **UF-ID:** UF-W113-04
- **Parent IF:** IF-W113
- **Goal:** Export the final obstacle layout to JSON for scene reproducibility.
- **I/O Contract:**
  - Input: `layout`: AnnotatedObstacleLayout; `output_path`: str
  - Output: JSON file; returns dict
- **Algorithm Summary:** dataclass → dict → json.dump
- **Edge Cases:** Empty layout → write empty list
- **Verification Plan:** `pytest test_obstacle.py::test_serialize`
- **Evidence Pack Fields:** output_path, n_objects

---

## IF-W114: Coordinate System & Transform Management

### UF-W114-01. Define global coordinate frame
- **UF-ID:** UF-W114-01
- **Parent IF:** IF-W114
- **Goal:** Establish the world coordinate frame (origin, axes, units) for the scene.
- **I/O Contract:**
  - Input: `origin`: float[3] (default [0,0,0]); `convention`: str ∈ {"Y-up-RH", "Z-up-RH"}
  - Output: `WorldFrame`: dataclass {origin[3], convention, unit="meters"}
- **Algorithm Summary:** Store convention; used as reference for all transform operations.
- **Edge Cases:** Unsupported convention → raise ValueError
- **Verification Plan:** `pytest test_transforms.py::test_world_frame`
- **Evidence Pack Fields:** origin, convention

### UF-W114-02. Convert local to world frame
- **UF-ID:** UF-W114-02
- **Parent IF:** IF-W114
- **Goal:** Transform entity positions/orientations from local object frame to world frame.
- **I/O Contract:**
  - Input: `local_pos`: float[3] (m); `transform`: Transform4x4 (4×4 float); `WorldFrame`
  - Output: `world_pos`: float[3] (m)
- **Algorithm Summary:** homogeneous matrix multiply; apply convention alignment if needed.
- **Edge Cases:** Non-invertible transform (determinant ≈ 0) → raise TransformError
- **Verification Plan:** `pytest test_transforms.py::test_local_to_world`; identity transform → same position
- **Evidence Pack Fields:** entity_id, local_pos, world_pos

### UF-W114-03. Time-index transforms
- **UF-ID:** UF-W114-03
- **Parent IF:** IF-W114
- **Goal:** Look up a time-indexed transform for a moving entity at a given tick.
- **I/O Contract:**
  - Input: `entity_id`: str; `tick_id`: int; `transform_sequence`: dict {entity_id → List[Transform4x4]}
  - Output: `Transform4x4` at tick_id
- **Algorithm Summary:** Direct index into pre-computed sequence; linear interpolation for sub-tick query.
- **Edge Cases:** tick_id out of range → clamp to last tick + warning; entity_id not found → raise KeyError
- **Verification Plan:** `pytest test_transforms.py::test_tick_lookup`
- **Evidence Pack Fields:** entity_id, tick_id, position

### UF-W114-04. Validate transform consistency
- **UF-ID:** UF-W114-04
- **Parent IF:** IF-W114
- **Goal:** Verify that all entity transforms across ticks are consistent (no teleportation, unit correctness).
- **I/O Contract:**
  - Input: `transform_sequence`: dict {entity_id → List[Transform4x4]}; `max_speed_m_per_s`: float
  - Output: `ConsistencyReport`: {passed: bool, violations: List[str]}
- **Algorithm Summary:** Compute per-tick displacement; flag if > max_speed × tick_duration_s
- **Edge Cases:** Single-tick sequence → no velocity to check; max_speed=None → skip velocity check
- **Verification Plan:** `pytest test_transforms.py::test_consistency`; inject teleportation → expect violation
- **Evidence Pack Fields:** n_violations, violating_entities

---

## IF-W115: Scene State Manager [NEW]

### UF-W115-01. Assemble SceneState at tick [NEW]
- **UF-ID:** UF-W115-01
- **Parent IF:** IF-W115
- **Goal:** Combine all scene components into a single typed SceneState object for tick_id.
- **I/O Contract:**
  - Input: `room`: RoomGeometry; `material_map`: MaterialMap; `obstacles`: ObstacleLayout; `src_traj`: List[SourceTrajectory]; `rec_traj`: List[ReceiverTrajectory]; `tick_id`: int
  - Output: `SceneState`: {tick_id, room, sources, receivers, materials, obstacles}
- **Algorithm Summary:** Slice trajectories at tick_id; populate SceneState dataclass.
- **Edge Cases:** tick_id beyond trajectory length → clamp + warning; empty source list → warn
- **Verification Plan:** `pytest test_scene_state.py::test_assemble`
- **Evidence Pack Fields:** tick_id, n_sources, n_receivers

### UF-W115-02. Serialize SceneState [NEW]
- **UF-ID:** UF-W115-02
- **Parent IF:** IF-W115
- **Goal:** Serialize SceneState to JSON for caching and debugging.
- **I/O Contract:**
  - Input: `state`: SceneState; `output_path`: str
  - Output: JSON file
- **Algorithm Summary:** Recursive dataclass → dict with numpy array serialization via tolist().
- **Edge Cases:** Very large trajectory → write only tick_id + reference, not full trajectory
- **Verification Plan:** `pytest test_scene_state.py::test_serialize_roundtrip`; serialize → deserialize → assert equal
- **Evidence Pack Fields:** tick_id, file_size_bytes

---

## IF-W121: Direct-Path Computation

### UF-W121-01. Compute distance and delay
- **UF-ID:** UF-W121-01
- **Parent IF:** IF-W121
- **Goal:** Compute Euclidean source-to-mic distance and corresponding time delay.
- **I/O Contract:**
  - Input: `src_pos`: float[3] (m, world); `mic_pos`: float[3] (m, world); `c`: float (m/s, default 343.0); `Fs`: int (Hz)
  - Output: `distance_m`: float; `delay_s`: float; `delay_samples`: int
- **Algorithm Summary:** distance = ‖src_pos − mic_pos‖₂; delay_s = distance/c; delay_samples = round(delay_s × Fs)
- **Edge Cases:** distance < 0.1 m → warning (near-field); distance > 25 m → warning (exceeds constraint)
- **Verification Plan:** `pytest test_direct_path.py::test_delay`; src=(1,0,0), mic=(0,0,0), c=343 → delay=1/343 s
- **Evidence Pack Fields:** src_id, mic_id, distance_m, delay_samples

### UF-W121-02. Compute distance attenuation
- **UF-ID:** UF-W121-02
- **Parent IF:** IF-W121
- **Goal:** Apply inverse-distance law to compute direct-path amplitude attenuation.
- **I/O Contract:**
  - Input: `distance_m`: float; `ref_distance_m`: float (default 1.0)
  - Output: `attenuation_linear`: float (≥ 0)
- **Algorithm Summary:** A = ref_distance / max(distance, 0.01). Clamped to [0,1] for near-field safety.
- **Edge Cases:** distance=0 → clamp to 0.01 m; distance > 25 m → A very small (normal)
- **Verification Plan:** `pytest test_direct_path.py::test_attenuation`; d=5 m, ref=1 → A=0.2
- **Evidence Pack Fields:** distance_m, attenuation_linear, attenuation_db

### UF-W121-03. Compute direction of arrival
- **UF-ID:** UF-W121-03
- **Parent IF:** IF-W121
- **Goal:** Compute azimuth and elevation of the source direction as seen from the microphone.
- **I/O Contract:**
  - Input: `src_pos`: float[3] (m); `mic_pos`: float[3] (m); `mic_orientation`: Quaternion
  - Output: `doa_az_rad`: float (−π, π]; `doa_el_rad`: float (−π/2, π/2]
- **Algorithm Summary:** direction = src_pos − mic_pos; transform to mic local frame via quaternion; convert to spherical.
- **Edge Cases:** src and mic co-located → raise PositionError; gimbal lock (el=±90°) → handle gracefully
- **Verification Plan:** `pytest test_direct_path.py::test_doa`; source at 90° az in world frame → verify
- **Evidence Pack Fields:** doa_az_deg, doa_el_deg

### UF-W121-04. Apply air attenuation and Doppler
- **UF-ID:** UF-W121-04
- **Parent IF:** IF-W121
- **Goal:** Apply frequency-dependent atmospheric absorption and optional Doppler shift for moving sources.
- **I/O Contract:**
  - Input: `distance_m`: float; `freq_hz`: float; `velocity_m_s`: float (source radial velocity, optional); `c`: float
  - Output: `air_atten_db`: float; `doppler_factor`: float (default 1.0 if velocity=0)
- **Algorithm Summary:** ISO 9613-1 air absorption α(f) dB/m × distance; Doppler = (c+v_obs)/(c−v_src)
- **Edge Cases:** velocity > 0.1c → warn (non-physical); distance=0 → air_atten=0
- **Verification Plan:** `pytest test_direct_path.py::test_air_attenuation`
- **Evidence Pack Fields:** distance_m, freq_hz, air_atten_db, doppler_factor

---

## IF-W122: Reflection & Reverberation Computation

### UF-W122-01. Early reflection path estimation
- **UF-ID:** UF-W122-01
- **Parent IF:** IF-W122
- **Goal:** Compute image source positions and path attributes for early reflections using ISM.
- **I/O Contract:**
  - Input: `room`: ShoeboxGeometry; `src_pos`: float[3]; `mic_pos`: float[3]; `ISM_order`: int (1–10)
  - Output: `ImageSources`: List[ImageSource{position[3], reflection_order, path_gain: float}]
- **Algorithm Summary:** Allen-Berkley ISM: enumerate image positions for orders 1..N; compute path length and product of reflection coefficients.
- **Edge Cases:** ISM_order > 7 for large room → warn about runtime; degenerate room (zero-size wall) → error
- **Verification Plan:** `pytest test_rir_generation.py::test_ism_image_sources`; order=1 → 6 images for shoebox
- **Evidence Pack Fields:** ISM_order, n_image_sources, compute_time_ms

### UF-W122-02. Late reverberation tail modeling
- **UF-ID:** UF-W122-02
- **Parent IF:** IF-W122
- **Goal:** Generate a stochastic late reverberation tail from RT60 and mixing time estimates.
- **I/O Contract:**
  - Input: `RT60`: float (s); `mixing_time_ms`: float; `Fs`: int; `seed`: int
  - Output: `late_tail`: float[N_samples] (exponentially decaying noise)
- **Algorithm Summary:** White noise shaped by exponential decay envelope e^(−6.9 × t / RT60); onset at mixing_time.
- **Edge Cases:** RT60=0 → empty tail; mixing_time > RIR duration → warn
- **Verification Plan:** `pytest test_rir_generation.py::test_late_tail`; measure T60 of output tail ≈ RT60 ± 10%
- **Evidence Pack Fields:** RT60_target, RT60_measured, mixing_time_ms, seed

### UF-W122-03. Frequency-dependent reverberation shaping
- **UF-ID:** UF-W122-03
- **Parent IF:** IF-W122
- **Goal:** Apply per-octave-band RT60 profiles to shape reverb frequency response.
- **I/O Contract:**
  - Input: `base_rir`: float[N]; `RT60_per_band`: float[6]; `octave_centers`: float[6]; `Fs`: int
  - Output: `shaped_rir`: float[N]
- **Algorithm Summary:** Bandpass filter RIR into octave bands; apply band-specific decay; sum bands.
- **Edge Cases:** All bands same RT60 → flat spectrum (special case); band overlap → use Butterworth with -3dB crossovers
- **Verification Plan:** `pytest test_rir_generation.py::test_spectral_shaping`
- **Evidence Pack Fields:** RT60_per_band[6]

### UF-W122-04. RT60 target fitting
- **UF-ID:** UF-W122-04
- **Parent IF:** IF-W122
- **Goal:** Adjust ISM/tail parameters so the final RIR matches a target RT60.
- **I/O Contract:**
  - Input: `rir`: float[N]; `RT60_target`: float (s); `Fs`: int
  - Output: `RT60_measured`: float (s); `fitting_error_s`: float
- **Algorithm Summary:** Schroeder backward integration; find −60 dB point; report deviation from target.
- **Edge Cases:** Energy decays faster than target → adjust late tail amplitude; RIR too short to reach −60 dB → use T20 extrapolation
- **Verification Plan:** `pytest test_rir_generation.py::test_rt60_fitting`; fitting_error < ±10% of target
- **Evidence Pack Fields:** RT60_target, RT60_measured, fitting_error_s

---

## IF-W123: Diffraction/Occlusion Approximation

### UF-W123-01. Visibility test
- **UF-ID:** UF-W123-01
- **Parent IF:** IF-W123
- **Goal:** Determine whether a line-of-sight exists between source and receiver given current obstacle layout.
- **I/O Contract:**
  - Input: `src_pos`: float[3]; `mic_pos`: float[3]; `obstacles`: ObstacleLayout
  - Output: `visible`: bool; `blocking_object_id`: str or None
- **Algorithm Summary:** Ray-AABB intersection test for each obstacle; if any AABB intersects the segment → occluded.
- **Edge Cases:** No obstacles → always visible; source or mic inside obstacle → force occluded
- **Verification Plan:** `pytest test_occlusion.py::test_visibility`
- **Evidence Pack Fields:** visible, blocking_object_id

### UF-W123-02. Occlusion loss estimation
- **UF-ID:** UF-W123-02
- **Parent IF:** IF-W123
- **Goal:** Estimate frequency-independent amplitude attenuation due to obstacle occlusion.
- **I/O Contract:**
  - Input: `src_pos`: float[3]; `mic_pos`: float[3]; `obstacle`: PlacedObject
  - Output: `loss_db`: float ∈ [0, 20]
- **Algorithm Summary:** Compute geometric shadow depth (fraction of obstacle cross-section in line of sight); map to dB loss 0–20 dB linear interpolation.
- **Edge Cases:** Full occlusion → 20 dB; partial occlusion → proportional; no occlusion → 0 dB
- **Verification Plan:** `pytest test_occlusion.py::test_occlusion_loss`
- **Evidence Pack Fields:** loss_db, occlusion_fraction

### UF-W123-03. Edge diffraction approximation
- **UF-ID:** UF-W123-03
- **Parent IF:** IF-W123
- **Goal:** Estimate diffraction path gain for partial blockage using Maekawa knife-edge model.
- **I/O Contract:**
  - Input: `src_pos`: float[3]; `mic_pos`: float[3]; `edge_pos`: float[3]; `freq_hz`: float
  - Output: `diffraction_gain_db`: float ∈ [−∞, 0]
- **Algorithm Summary:** Compute Fresnel number N from geometry; Maekawa: gain = −10 log₁₀(3 + 20N) for N > 0
- **Edge Cases:** N < 0 (source in diffraction shadow) → gain = 0 dB; freq=0 → error
- **Verification Plan:** `pytest test_occlusion.py::test_maekawa`; compare to analytical Maekawa table values
- **Evidence Pack Fields:** fresnel_number, diffraction_gain_db, freq_hz

### UF-W123-04. Dynamic occlusion update
- **UF-ID:** UF-W123-04
- **Parent IF:** IF-W123
- **Goal:** Re-evaluate occlusion state when source/mic has moved beyond update threshold.
- **I/O Contract:**
  - Input: `prev_state`: OcclusionResult; `curr_src_pos`: float[3]; `curr_mic_pos`: float[3]; `threshold_m`: float (default 0.1)
  - Output: `OcclusionResult` (updated or cached); `updated`: bool
- **Algorithm Summary:** Compute displacement from last evaluation position; if > threshold → re-evaluate; else return cached.
- **Edge Cases:** First call → always evaluate; threshold=0 → always re-evaluate
- **Verification Plan:** `pytest test_occlusion.py::test_dynamic_update`
- **Evidence Pack Fields:** updated, displacement_m

---

## IF-W124: RIR/BRIR Generation & Rendering

### UF-W124-01. Generate static RIR
- **UF-ID:** UF-W124-01
- **Parent IF:** IF-W124
- **Goal:** Assemble complete RIR from direct path, image sources, and late tail.
- **I/O Contract:**
  - Input: `direct`: DirectPath; `reflections`: ImageSources; `late_tail`: float[N]; `occlusion`: OcclusionResult; `Fs`: int
  - Output: `RIR`: {h: float[N_samples], rt60_measured: float, drr_db: float, peak_delay_samples: int}
- **Algorithm Summary:** Place Dirac impulses at delay positions with gain; add late tail onset at mixing time; apply occlusion loss to direct path.
- **Edge Cases:** All image sources outside RIR window → ISM order may be too low; warn if DRR < −10 dB
- **Verification Plan:** `pytest test_rir_generation.py::test_static_rir`
- **Evidence Pack Fields:** rt60_measured, drr_db, rir_length_samples

### UF-W124-02. Generate BRIR
- **UF-ID:** UF-W124-02
- **Parent IF:** IF-W124
- **Goal:** Convolve monaural RIR with left/right HRTF filters for a given head orientation.
- **I/O Contract:**
  - Input: `rir`: float[N]; `hrtf_db`: HRTFDatabase; `doa_az_rad`: float; `doa_el_rad`: float; `subject_id`: int
  - Output: `BRIR`: float[2×N] (left, right channels)
- **Algorithm Summary:** Interpolate HRTF filters at (az, el) using spherical interpolation; convolve RIR with each ear filter.
- **Edge Cases:** DOA outside HRTF grid range → clamp to nearest measured point + warning; subject_id not in DB → raise KeyError
- **Verification Plan:** `pytest test_brir.py::test_brir_ild_itd`
- **Evidence Pack Fields:** subject_id, doa_az_deg, doa_el_deg, ild_db, itd_us

### UF-W124-03. Segment-wise dynamic RIR interpolation
- **UF-ID:** UF-W124-03
- **Parent IF:** IF-W124
- **Goal:** Interpolate between consecutive static RIRs for smooth dynamic convolution.
- **I/O Contract:**
  - Input: `rir_start`: float[N]; `rir_end`: float[N]; `alpha`: float ∈ [0,1] (interpolation factor)
  - Output: `rir_interp`: float[N]
- **Algorithm Summary:** Linear interpolation: h = (1−α)×h_start + α×h_end. For large phase differences, apply time-warped interpolation.
- **Edge Cases:** rir_start and rir_end have different lengths → zero-pad shorter; alpha outside [0,1] → clamp
- **Verification Plan:** `pytest test_dynamic_render.py::test_rir_interpolation`; alpha=0 → rir_start, alpha=1 → rir_end
- **Evidence Pack Fields:** alpha, rms_interpolation_error

### UF-W124-04. Render waveform by convolution
- **UF-ID:** UF-W124-04
- **Parent IF:** IF-W124
- **Goal:** Convolve dry source signal with RIR to produce observed microphone signal.
- **I/O Contract:**
  - Input: `source_signal`: float[N_src]; `rir`: float[N_rir]; `mode`: str ∈ {"full","same","OLA"}
  - Output: `rendered`: float[N_out]; `N_out` = N_src + N_rir − 1 for "full"
- **Algorithm Summary:** scipy.signal.fftconvolve for static; OLA overlap-add for dynamic segments.
- **Edge Cases:** Source signal or RIR empty → raise; N_rir > N_src → full mode pads
- **Verification Plan:** `pytest test_rir_generation.py::test_convolution`
- **Evidence Pack Fields:** N_src, N_rir, N_out, mode

---

## IF-W131–W134: Dynamic Motion Simulation
*(UF blocks follow same template; abbreviated here for brevity — full I/O contracts in uf_detail_motion.md)*

### UF-W131-01. Define motion primitives
- **I/O Contract:**
  - Input: `motion_type`: str; `params`: dict; `room_bbox`: AABB; `duration_s`: float; `seed`: int
  - Output: `MotionPrimitive`: callable(t) → position[3]
- **Edge Cases:** Waypoint list outside room → clamp to room interior; duration=0 → static position

### UF-W131-02. Generate velocity/orientation profiles
- **I/O Contract:**
  - Input: `positions`: float[T×3]; `tick_rate_hz`: float
  - Output: `velocities`: float[T×3] (m/s); `orientations`: float[T] (yaw, rad)
- **Edge Cases:** |velocity| > 2.0 m/s → warn and clamp

### UF-W131-03. Enforce path constraints
- **I/O Contract:**
  - Input: `trajectory`: float[T×3]; `room_bbox`: AABB; `min_wall_dist_m`: float
  - Output: `constrained_trajectory`: float[T×3]
- **Algorithm Summary:** Project positions violating wall distance back to valid region

### UF-W131-04. Export time-stamped trajectories
- **I/O Contract:**
  - Input: `trajectory`: Trajectory; `output_path`: str
  - Output: JSON {tick_id, timestamp_s, position[3], velocity[3], orientation}[]

---

## IF-W141–W144: Capture Device Realism
*(UF blocks — full I/O contracts for key functions)*

### UF-W141-01. Apply frequency response profile
- **I/O Contract:**
  - Input: `signal`: float[N]; `freq_response`: float[F] (dB at F frequency bins); `Fs`: int
  - Output: `filtered_signal`: float[N]
- **Algorithm Summary:** Design FIR filter from freq_response via frequency sampling method; apply via convolution

### UF-W141-03. Apply directional pickup pattern
- **I/O Contract:**
  - Input: `signal`: float[N]; `doa_az_rad`: float; `doa_el_rad`: float; `pattern_type`: str ∈ {"omni","cardioid","supercardioid","figure8"}
  - Output: `pattern_gain`: float; `signal_gained`: float[N]
- **Algorithm Summary:** pattern_gain = pattern_fn(az, el); signal × pattern_gain

### UF-W143-01. Add self-noise floor
- **I/O Contract:**
  - Input: `signal`: float[N]; `noise_floor_dbfs`: float; `Fs`: int; `seed`: int
  - Output: `noisy_signal`: float[N]; `snr_db`: float
- **Algorithm Summary:** Gaussian noise with power = 10^(noise_floor_dbfs/10) × full-scale; add to signal

### UF-W143-03. Clip/saturate under overload
- **I/O Contract:**
  - Input: `signal`: float[N]; `clip_threshold_dbfs`: float (default 0.0)
  - Output: `clipped_signal`: float[N]; `clipped`: bool; `n_clipped_samples`: int
- **Algorithm Summary:** clip_level = 10^(threshold/20); np.clip(signal, −clip_level, +clip_level)

---

## IF-W151–W155: Simulator Orchestration

### UF-W151-01. Define scene config schema
- **I/O Contract:**
  - Input: schema definition (Pydantic model or JSON Schema)
  - Output: `SceneConfigSchema`: versioned Pydantic model v{MAJOR}.{MINOR}.{PATCH}
- **Key fields:** room, materials, sources[], receivers[], motion, impairments, seed, output_dir

### UF-W151-02. Validate config completeness
- **I/O Contract:**
  - Input: `raw_config`: dict; `schema_version`: str
  - Output: `SceneConfig` (validated); raises `ValidationError` on failure with field path in message

### UF-W152-01. Queue simulation jobs
- **I/O Contract:**
  - Input: `configs`: List[SceneConfig]; `checkpoint_file`: path
  - Output: `JobQueue`: priority queue with checkpoint state

### UF-W152-02. Parallelize scene rendering
- **I/O Contract:**
  - Input: `job_queue`: JobQueue; `worker_count`: int; `output_dir`: str
  - Output: `ExecutionSummary` {n_completed, n_failed, elapsed_s}
- **Algorithm Summary:** multiprocessing.Pool with worker_count processes; each worker calls simulate(SceneConfig)

### UF-W155-01. Validate acoustic plausibility [NEW]
- **UF-ID:** UF-W155-01
- **Parent IF:** IF-W155
- **Goal:** Check that scene configuration will produce physically realizable acoustic conditions.
- **I/O Contract:**
  - Input: `room`: RoomGeometry; `materials`: MaterialMap; `sources`: List[SourceConfig]; `receivers`: List[ReceiverConfig]
  - Output: `PlausibilityReport` {passed: bool, predicted_RT60: float, predicted_DRR_db: float, warnings: List[str]}
- **Algorithm Summary:** Sabine RT60 estimate from volume/absorption sum; DRR estimate from direct-path distance; check against [AC-04] bounds.
- **Edge Cases:** All surfaces fully absorbing (α=1) → RT60=0 (anechoic, valid); inconsistent material sum → warn
- **Verification Plan:** `pytest test_scene_validation.py::test_acoustic_plausibility`
- **Evidence Pack Fields:** predicted_RT60, predicted_DRR_db, passed
