# W100000 Clarification Log
**Format:** Q (Ambiguity) → A (Resolution) → Impact

---

## CL-01. Audio sample rate
**Q:** Section 2 mentions waveform export but no sample rate is defined. Which rates must be supported?
**A (assumed):** Primary target is 16 kHz for speech separation tasks; 48 kHz optional for high-fidelity output. Simulator must support configurable Fs ∈ {8000, 16000, 22050, 44100, 48000} Hz.
**Impact:** RIR length in samples = RIR_duration_sec × Fs. All UF-W124-XX outputs must be Fs-parameterized.

## CL-02. "Dynamic scene" — update granularity
**Q:** UF-W133-01 says "synchronize by simulation tick" but tick duration is undefined.
**A (assumed):** Simulation tick = one audio segment of length 20–50 ms (configurable). Scene state may update at 20 Hz (50 ms segments) to 100 Hz (10 ms segments).
**Impact:** W134000 segment length directly controls convolution accuracy vs. runtime.

## CL-03. Room geometry scope
**Q:** UF-W111-01 lists shoebox, corridor, hall, custom mesh. What is the maximum room volume?
**A (assumed):** Volume range 10 m³ (small booth) to 5000 m³ (large hall). Shoebox must support dimensions up to 30 m × 20 m × 10 m.
**Impact:** ISM (Image Source Method) order must be bounded; ray-count for ray-tracing must scale.

## CL-04. Number of sources and microphones
**Q:** No maximum count defined anywhere.
**A (assumed):** Up to 8 simultaneous active speech sources; up to 64-channel microphone arrays; up to 2 binaural listeners.
**Impact:** Memory budget scales as O(N_src × N_mic × RIR_length). Must be validated in W152000.

## CL-05. RIR length
**Q:** Section 5 mentions RT60 fitting but maximum RIR duration is undefined.
**A (assumed):** RIR duration = max(3 × RT60_target, 0.5 s), capped at 4.0 s. At 16 kHz this is 64,000 samples maximum.
**Impact:** Convolution cost and memory directly bounded.

## CL-06. Real-time vs. offline processing
**Q:** Section 2 implies both streaming (W144000 packet loss) and batch export. Is real-time rendering required?
**A (assumed):** Primary mode is offline batch generation for dataset creation. Real-time rendering (latency < 50 ms) is a stretch goal, not a hard requirement for V1.
**Impact:** W134000 dynamic convolution strategy can prioritize accuracy over latency.

## CL-07. HRTF / Binaural model source
**Q:** UF-W124-02 mentions BRIR but no HRTF database is specified.
**A (assumed):** Default to CIPIC HRTF database (45 subjects, 25×50 measurement grid). Subject selection by scene seed. Spherical interpolation for off-grid angles.
**Impact:** Binaural rendering quality and angular resolution bounded by CIPIC grid (minimum 5° elevation, 5° azimuth spacing in dense region).

## CL-08. "Reproducibility" scope
**Q:** UF-W151-03 mentions seed-based deterministic reproduction. Does this include material variation and trajectory noise?
**A (assumed):** Full determinism required: given identical (config, seed) pair, simulator must produce bit-identical waveforms across runs and platforms (modulo IEEE 754 platform differences).
**Impact:** All stochastic elements (W112-03, W132-03, W143-01) must use seeded RNG passed through SceneConfig.

## CL-09. Occlusion model complexity
**Q:** W123000 says "approximation" — is geometric (ray-based) or wave-based diffraction required?
**A (assumed):** Geometric acoustics only for V1. Occlusion = binary visibility test + frequency-independent attenuation loss 0–20 dB. Edge diffraction = Maekawa approximation for knife-edge obstacles only.
**Impact:** Wave-based diffraction (BEM, FDTD) is out of scope for V1.

## CL-10. Downstream consumer interface
**Q:** "Write manifest for downstream dataset builder" (UF-W153-04) — what format does the dataset builder expect?
**A (assumed):** JSON manifest per scene with fields: scene_id, source_count, channel_count, audio_files[], rir_files[], metadata.json path, acoustic_summary.json path. Audio format: 32-bit float WAV, channel-major ordering.
**Impact:** W153000 export schema must be frozen before W152000 batch runner is implemented.
