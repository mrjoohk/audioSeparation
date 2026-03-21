# W100000 Assumptions and Constraints
**Date:** 2026-03-21

---

## A. Physical / Acoustic Constraints

| ID | Constraint | Value / Range | Rationale |
|----|-----------|---------------|-----------|
| AC-01 | Sample rates supported | {8000, 16000, 22050, 44100, 48000} Hz | Speech separation typically 16 kHz; HQ output 48 kHz |
| AC-02 | Room volume | 10 m³ – 5000 m³ | Booth to large hall; beyond 5000 m³ = outdoor (out of scope V1) |
| AC-03 | Room dimensions (shoebox) | Each side 1–30 m | Practical indoor limits |
| AC-04 | RT60 range | 0.05 s – 5.0 s | Anechoic chamber to cathedral |
| AC-05 | RIR maximum duration | max(3×RT60, 0.5 s), capped 4.0 s | Energy cutoff at −60 dB; 4 s at 48 kHz = 192,000 samples |
| AC-06 | Maximum active sources | 8 simultaneous speech sources | Practical cocktail-party scenario |
| AC-07 | Maximum microphone channels | 64 channels per array, 2 binaural listeners | Covers ULA, circular, binaural |
| AC-08 | Source-mic distance range | 0.1 m – 25 m | Near-field limit 0.1 m; far-field practical max 25 m indoors |
| AC-09 | Speed of sound | 343 m/s at 20°C (configurable 330–350 m/s) | Air temperature variation |
| AC-10 | Frequency range for absorption | 125, 250, 500, 1000, 2000, 4000 Hz octave bands | Standard ISO 354 measurement bands |

---

## B. Computational / System Constraints

| ID | Constraint | Value / Range | Rationale |
|----|-----------|---------------|-----------|
| CC-01 | Processing mode | Offline batch (primary); real-time stretch goal | Dataset generation use case |
| CC-02 | Batch throughput target | ≥ 1000 scenes/hour on 8-core CPU | Enables dataset of 100k scenes in ≤ 100 hours |
| CC-03 | Memory per worker | ≤ 4 GB RAM per parallel worker | Standard workstation node budget |
| CC-04 | RNG reproducibility | Bit-identical given (config, seed) pair | Deterministic dataset regeneration |
| CC-05 | Config schema versioning | Semantic versioning (MAJOR.MINOR.PATCH) | Breaking changes bump MAJOR |
| CC-06 | Audio output format | 32-bit float PCM WAV, channel-major | Lossless; compatible with torchaudio, soundfile |
| CC-07 | Metadata format | JSON (UTF-8, indented) | Human-readable; machine-parseable |

---

## C. Algorithm / Method Assumptions

| ID | Assumption | Detail |
|----|-----------|--------|
| AM-01 | Reflection model | Image Source Method (ISM) for shoebox; ray tracing for custom mesh |
| AM-02 | ISM reflection order | Configurable 1–10; default 3 for speed, 7 for accuracy |
| AM-03 | Diffraction model | Maekawa knife-edge approximation only (V1); wave-based out of scope |
| AM-04 | HRTF database | CIPIC 45-subject database; spherical interpolation; subject selected by seed |
| AM-05 | Air absorption | ISO 9613-1 frequency-dependent attenuation (dB/m per octave band) |
| AM-06 | Dynamic convolution | OLA/OLS with segment length = 20 ms; re-render threshold = 5 cm position change |
| AM-07 | Noise model | Additive white Gaussian noise for self-noise; correlated noise optional |
| AM-08 | Codec simulation | Bandwidth limitation via FIR filter; no proprietary codec bit-exact simulation |

---

## D. Scope Exclusions (Out of Scope for V1)

| ID | Excluded Capability | Reason |
|----|--------------------|-|
| EX-01 | Outdoor / open-field simulation | No room boundaries; different propagation model |
| EX-02 | Wave-based diffraction (BEM, FDTD) | Computational cost incompatible with CC-02 |
| EX-03 | Moving obstacles during scene | Static obstacle layout per scene tick (obstacles don't move) |
| EX-04 | Real-time streaming output | Latency < 50 ms; deferred to V2 |
| EX-05 | Proprietary codec bit-exact simulation | Licensing; use perceptual approximation only |
| EX-06 | GPU-accelerated convolution | V1 targets CPU; GPU backend is V2 extension |
