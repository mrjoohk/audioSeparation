# W100000 Requirements
**Date:** 2026-03-21
**Format:** Core Engineering REQ Block

---

## REQ-W01. Room geometry representation

- **ID:** REQ-W01
- **Context:** The simulator must represent diverse indoor room geometries to cover training distribution for speech separation.
- **Inputs:** Room type ∈ {shoebox, corridor, hall, mesh}, dimension parameters (float, meters), material assignment map
- **Outputs:** Validated RoomGeometry object with surface list, bounding volume, material map
- **Constraints:** Room volume 10–5000 m³; all surfaces must form a closed manifold; mesh must be watertight
- **Acceptance Criteria:**
  - Given a shoebox config (L×W×H), When geometry is built, Then bounding volume error ≤ 0.001 m³ vs. analytical L×W×H
  - Given an invalid (non-closed) mesh, When validation runs, Then error is raised and simulation is blocked
  - Given 1000 random shoebox configs, When batch-built, Then 100% pass manifold validation
- **Tests:** unit: test_room_geometry.py; integration: test_scene_builder.py
- **Evidence:** geometry_validation_log.json

---

## REQ-W02. Frequency-dependent material absorption

- **ID:** REQ-W02
- **Context:** Acoustic absorption must be spectrally accurate to produce realistic RT60 and frequency coloring in reverb.
- **Inputs:** Material class name (str), octave-band absorption coefficients α[6] (float, 0–1), scattering coefficients σ[6] (float, 0–1)
- **Outputs:** Validated MaterialSpec object registered in material database
- **Constraints:** α values per band ∈ [0.0, 1.0]; at least 6 standard ISO octave bands required
- **Acceptance Criteria:**
  - Given a concrete material (α ≈ 0.02 at 500 Hz), When assigned to room surfaces, Then simulated RT60 at 500 Hz is within ±15% of Sabine/Eyring prediction
  - Given stochastic variation seed, When material coefficients are sampled, Then reproduced identically with same seed
- **Tests:** unit: test_material_db.py; integration: test_rt60_fit.py
- **Evidence:** rt60_vs_sabine_comparison.csv

---

## REQ-W03. Direct-path propagation accuracy

- **ID:** REQ-W03
- **Context:** Direct-path delay and attenuation are the foundation for source localization and time-difference-of-arrival (TDOA) based separation.
- **Inputs:** Source position p_s (3D float, m, world frame), Receiver position p_r (3D float, m, world frame), Fs (int, Hz)
- **Outputs:** Time delay τ (float, s), attenuation A (float, linear), DOA azimuth/elevation (float, radians)
- **Constraints:** Distance range 0.1–25 m; delay quantized to 1/Fs resolution; DOA computed in spherical coordinates
- **Acceptance Criteria:**
  - Given source at (1,0,0) and mic at (0,0,0), When direct path computed at Fs=16000, Then delay = 1/343 s ± 1 sample, attenuation = 1/1 = 1.0 (0 dB)
  - Given source at (5,0,0) and mic at (0,0,0), When direct path computed, Then attenuation = 1/5 ± 0.1% (inverse-distance law)
  - Given 10,000 random source-mic pairs, When TDOA computed for 2-mic array, Then angular error < 1° at SNR ≥ 20 dB
- **Tests:** unit: test_direct_path.py
- **Evidence:** direct_path_accuracy_table.csv

---

## REQ-W04. RIR generation accuracy

- **ID:** REQ-W04
- **Context:** Room impulse responses are the core acoustic artifact; their accuracy determines downstream task performance.
- **Inputs:** SceneState (room, source pos, mic pos, material map), Fs (int, Hz), ISM order (int, 1–10)
- **Outputs:** RIR array h[N_samples] (float32, linear amplitude), associated metadata (RT60_measured, DRR, peak_delay)
- **Constraints:** RIR duration ≤ 4.0 s; energy must decay ≥ 60 dB from peak to end; 1000 RIRs generated per second (Fs=16kHz, ISM order=3)
- **Acceptance Criteria:**
  - Given shoebox with known Sabine RT60 = 0.5 s, When RIR is generated (ISM order 7), Then measured RT60 (from energy decay) is within ±10% of 0.5 s
  - Given anechoic config (α=1.0 all surfaces), When RIR generated, Then DRR > 40 dB
  - Given same (scene, seed) twice on same machine, When RIR generated, Then waveforms are bit-identical
  - Given batch of 1000 scenes (Fs=16kHz), When RIRs generated on 8-core CPU, Then throughput ≥ 1000 RIRs/s
- **Tests:** unit: test_rir_generation.py; integration: test_rir_rt60.py; perf: bench_rir_throughput.py
- **Evidence:** rir_accuracy_report.json, rir_throughput_bench.csv

---

## REQ-W05. Binaural / BRIR rendering

- **ID:** REQ-W05
- **Context:** Binaural output enables training models for headphone-based spatial audio and earable devices.
- **Inputs:** SceneState, HRTF subject ID (int or 'random'), head orientation (yaw/pitch/roll, float, degrees)
- **Outputs:** BRIR[2 × N_samples] (float32, left/right channels), associated HRTF metadata
- **Constraints:** HRTF angular resolution interpolation error < 3° perceived direction; subject ID randomized by scene seed
- **Acceptance Criteria:**
  - Given source at 90° azimuth (right), When BRIR rendered, Then ILD > 5 dB at 2 kHz
  - Given source at 0° azimuth (front), When BRIR rendered, Then ITD < 50 µs (|ITD| < 50 µs)
  - Given 100 random head orientations, When BRIRs rendered, Then localization error (Rayleigh model) < 5° RMS
- **Tests:** unit: test_brir_generation.py; integration: test_binaural_localization.py
- **Evidence:** binaural_ild_itd_table.csv

---

## REQ-W06. Dynamic scene convolution

- **ID:** REQ-W06
- **Context:** Moving sources/listeners require time-varying convolution without audible artifacts.
- **Inputs:** Source trajectory (list of SceneState by tick), segment length T_seg (float, ms), Fs (int, Hz)
- **Outputs:** Time-continuous rendered waveform (float32, multichannel), tick-aligned RIR log
- **Constraints:** Segment length 10–100 ms; re-render triggered when position changes > 5 cm; crossfade between segments to suppress clicks
- **Acceptance Criteria:**
  - Given source moving at 1 m/s, segment length = 20 ms, When rendered, Then no click artifacts (energy discontinuity < −60 dB at segment boundaries)
  - Given static source (trajectory = constant), When dynamic render used, Then output = static convolution output within −80 dB RMS error
- **Tests:** unit: test_dynamic_render.py; integration: test_moving_source.py
- **Evidence:** dynamic_render_artifact_analysis.png

---

## REQ-W07. Microphone array geometry accuracy

- **ID:** REQ-W07
- **Context:** Array topology accuracy directly affects beamforming and TDOA estimation in downstream algorithms.
- **Inputs:** Array template (str: ULA/circular/custom), nominal element positions (N×3 float, m), perturbation σ (float, m), seed (int)
- **Outputs:** Effective element positions (N×3 float, m), exported array metadata JSON
- **Constraints:** Position perturbation σ ≤ 5 mm; clock skew ≤ 1 sample at Fs=16kHz
- **Acceptance Criteria:**
  - Given ULA with d=5 cm spacing, When positions exported, Then element spacing error < 0.1 mm (before perturbation)
  - Given perturbation σ=2 mm, When 1000 arrays generated, Then per-element displacement follows N(0, σ²) within KS-test p > 0.05
- **Tests:** unit: test_array_geometry.py
- **Evidence:** array_position_stats.csv

---

## REQ-W08. Sensor noise and gain modeling

- **ID:** REQ-W08
- **Context:** Microphone self-noise and gain variation must match practical SNR distributions seen in real recordings.
- **Inputs:** Clean signal x[N] (float32), noise floor level (float, dBFS), gain (float, dB), clip threshold (float, dBFS)
- **Outputs:** Degraded signal x_noisy[N] (float32), per-channel SNR (float, dB)
- **Constraints:** Self-noise floor range −70 to −30 dBFS; gain range −20 to +30 dB; clipping at 0 dBFS
- **Acceptance Criteria:**
  - Given speech signal at −20 dBFS and noise floor at −60 dBFS, When noise applied, Then measured SNR ∈ [38, 42] dB
  - Given gain = +12 dB and 0 dBFS clip, When signal exceeds threshold, Then output is hard-clipped and metadata tag 'clipped=True' is set
- **Tests:** unit: test_sensor_noise.py
- **Evidence:** snr_distribution_plot.png

---

## REQ-W09. Job configuration and reproducibility

- **ID:** REQ-W09
- **Context:** Dataset generation requires exact reproducibility for scientific validity and debugging.
- **Inputs:** Scene config (YAML/JSON), global seed (int), config schema version (str)
- **Outputs:** Validated SceneConfig object; deterministic simulation state
- **Constraints:** Schema must validate in < 10 ms; seed must produce bit-identical output across re-runs on same platform
- **Acceptance Criteria:**
  - Given identical (config.yaml, seed=42) run twice, When waveforms compared, Then MD5 of all output WAV files match
  - Given config missing required field, When validated, Then ValidationError raised with field name in message
  - Given config schema v1.2 and simulator v1.3, When loaded, Then backward-compatible fields are accepted; unknown fields trigger warning only
- **Tests:** unit: test_config_schema.py; integration: test_reproducibility.py
- **Evidence:** reproducibility_hash_log.csv

---

## REQ-W10. Batch execution throughput

- **ID:** REQ-W10
- **Context:** Generating 100k-scene datasets requires scalable parallel execution.
- **Inputs:** Job queue (list of N SceneConfigs), worker count W (int), output_dir (str)
- **Outputs:** N rendered scene directories; execution summary (time, errors, throughput)
- **Constraints:** ≥ 1000 scenes/hour on 8-core CPU (Fs=16kHz, 2 sources, 4 mics, ISM order 3, 10 s duration); worker memory ≤ 4 GB each
- **Acceptance Criteria:**
  - Given 1000 scene configs, When batch run on 8-core CPU, Then all 1000 complete in ≤ 3600 s with 0 silent failures
  - Given 10% of jobs fail with exception, When batch resumes from checkpoint, Then only failed jobs are re-run, completed jobs are skipped
- **Tests:** integration: test_batch_runner.py; perf: bench_batch_throughput.py
- **Evidence:** batch_runtime_log.json

---

## REQ-W11. Metadata and manifest export

- **ID:** REQ-W11
- **Context:** Downstream dataset builder must be able to load all scene artifacts without re-running simulation.
- **Inputs:** Rendered scene directory (paths to WAV, RIR, metadata)
- **Outputs:** scene_manifest.json (per scene), dataset_index.json (all scenes)
- **Constraints:** Manifest schema v1.0 with fields: scene_id, source_count, channel_count, audio_files[], rir_files[], acoustic_summary{RT60, DRR, SNR, DOA[]}
- **Acceptance Criteria:**
  - Given rendered scene, When manifest exported, Then all audio_files[] paths exist and are non-empty WAV files
  - Given dataset_index.json, When loaded by dataset builder stub, Then all scenes accessible with no missing keys
  - Given acoustic_summary, When RT60 field read, Then value matches measured RT60 from RIR ± 5 ms
- **Tests:** unit: test_manifest_export.py; integration: test_dataset_builder_interface.py
- **Evidence:** manifest_schema_validation.log

---

## REQ-W12. Validation and debugging visualization

- **ID:** REQ-W12
- **Context:** Developers need visual tools to verify scene layout, RIR plausibility, and waveform output without running full pipeline.
- **Inputs:** SceneState or rendered scene directory
- **Outputs:** Room layout plot (PNG), RIR plot (PNG), waveform plot per channel (PNG), RT60 bar chart (PNG)
- **Constraints:** Visualization must complete in < 5 s per scene; no GUI required (headless matplotlib acceptable)
- **Acceptance Criteria:**
  - Given SceneState, When room plot generated, Then all source and mic positions visible within room boundary
  - Given RIR, When energy decay plotted, Then −60 dB line correctly intersects measured RT60 point
- **Tests:** unit: test_visualization.py
- **Evidence:** sample_viz_outputs/

---

## REQ-W13. Occlusion and diffraction modeling

- **ID:** REQ-W13
- **Context:** Obstacles between source and microphone reduce direct-path energy; this must be captured for realistic occlusion scenarios.
- **Inputs:** Source position, receiver position, obstacle geometry list, frequency (octave band center, Hz)
- **Outputs:** Occlusion attenuation loss (float, dB) per octave band, visibility flag (bool)
- **Constraints:** Maekawa approximation; loss range 0–20 dB; dynamic update when source/mic moves > 10 cm
- **Acceptance Criteria:**
  - Given source and mic with no obstacle between them, When visibility test run, Then visibility=True, loss=0 dB
  - Given knife-edge obstacle perfectly between source and mic, When Maekawa approximation applied, Then loss is within ±3 dB of analytical Maekawa result
- **Tests:** unit: test_occlusion.py
- **Evidence:** occlusion_vs_analytical.csv

---

## REQ-W14. Source trajectory generation

- **ID:** REQ-W14
- **Context:** Realistic motion patterns (walking, stationary, turning) are needed for training separation models on moving sources.
- **Inputs:** Motion primitive type (str), room geometry (for boundary constraints), duration (float, s), seed (int)
- **Outputs:** Trajectory object: list of (position [3D float, m], velocity [3D float, m/s], orientation [float, rad]) at each tick
- **Constraints:** Trajectory must remain inside room; min distance to wall ≥ 0.5 m; max speed ≤ 2.0 m/s (walking)
- **Acceptance Criteria:**
  - Given linear motion primitive, room 5×5×3 m, duration=10 s, When trajectory generated, Then all 500 tick positions (Fs=50Hz tick) are inside room bounds
  - Given random-walk primitive with seed=42, When generated twice, Then position sequences are identical
- **Tests:** unit: test_trajectory_gen.py
- **Evidence:** trajectory_boundary_check.log

---

## REQ-W15. Codec and channel impairment modeling

- **ID:** REQ-W15
- **Context:** Real-world audio is often transmitted over compressed or lossy channels; impairment simulation increases dataset diversity.
- **Inputs:** Clean rendered waveform x[N] (float32), impairment config (type, parameters)
- **Outputs:** Impaired waveform x_impaired[N] (float32), impairment metadata tag
- **Constraints:** Bandwidth limitation: FIR lowpass; lossy codec: MP3-like spectral hole simulation; packet loss: configurable PER (packet error rate) 0–20%
- **Acceptance Criteria:**
  - Given bandwidth limit to 4 kHz (telephone), When filtered, Then spectral energy above 4.5 kHz < −40 dB
  - Given PER=10%, duration=10 s, segment=20 ms, When packet loss simulated, Then ~50±10 segments zeroed (Bernoulli p=0.1)
- **Tests:** unit: test_codec_impairment.py
- **Evidence:** impairment_spectral_analysis.png
