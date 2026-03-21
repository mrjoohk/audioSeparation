# W100000 Verification Plan
**Date:** 2026-03-21
**Stage:** 8 — Verification & Evidence Planning

---

## 1. Test Hierarchy

```
E2E Tests         — Full pipeline: config → rendered scenes → manifest
Integration Tests — IF-level: multi-UF data flow verified
Unit Tests        — UF-level: single function with mocked inputs
Performance Tests — Throughput and memory benchmarks
```

---

## 2. Unit Test Plan (per UF)

### Module W111: Room Geometry
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W111-01 | UF-W111-01 | shoebox L=5, W=4, H=3 | surface_count=6, volume=60 m³ | volume error ≤ 0.001 m³ |
| UT-W111-02 | UF-W111-02 | valid OBJ watertight mesh | MeshRoom with is_watertight=True | 100% pass |
| UT-W111-03a | UF-W111-03 | non-watertight mesh (1 hole) | is_valid=False, open_edges ≥ 1 | always detected |
| UT-W111-03b | UF-W111-03 | valid shoebox mesh | is_valid=True, open_edges=0 | 100% pass |
| UT-W111-04 | UF-W111-04 | shoebox 5×4×3 | AABB volume=60 m³ | error ≤ 0.001 m³ |

### Module W112: Material Properties
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W112-01 | UF-W112-01 | concrete α=[0.02,0.02,0.03,0.04,0.05,0.05] | registered in DB | α[i] ∈ [0,1] |
| UT-W112-02 | UF-W112-02 | 6 surfaces + material assignments | MaterialMap with 6 entries | no missing keys |
| UT-W112-03a | UF-W112-03 | seed=42, σ=0.05 × 2 runs | identical output | bit-identical |
| UT-W112-03b | UF-W112-03 | σ=0.2, 1000 samples | α samples ∈ [0,1] | 100% within bounds |

### Module W121: Direct Path
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W121-01 | UF-W121-01 | src=(1,0,0), mic=(0,0,0), Fs=16000 | delay=1/343 s, samples=46 | ±1 sample |
| UT-W121-02 | UF-W121-02 | d=5 m, ref=1 m | attenuation=0.2 (−14 dB) | ±0.1% |
| UT-W121-03 | UF-W121-03 | src at 90° az, 0° el | doa_az ≈ π/2 | ±0.01 rad |
| UT-W121-04 | UF-W121-04 | d=10 m, f=4000 Hz | air_atten ≈ 0.12 dB (ISO 9613) | ±0.01 dB |

### Module W122: Reverberation
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W122-01 | UF-W122-01 | shoebox 5×4×3, ISM_order=1 | 6 image sources | exactly 6 |
| UT-W122-02 | UF-W122-02 | RT60=0.5 s, Fs=16000, seed=1 | measured T60 from tail | ±10% = ±50 ms |
| UT-W122-04 | UF-W122-04 | RIR with RT60≈0.3 s, target=0.5 s | fitting_error | ≤ 50 ms |

### Module W123: Occlusion
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W123-01a | UF-W123-01 | src, mic, no obstacles | visible=True | always |
| UT-W123-01b | UF-W123-01 | obstacle on line of sight | visible=False | always |
| UT-W123-03 | UF-W123-03 | Fresnel N=1.0, f=1000 Hz | gain ≈ −13 dB (Maekawa) | ±3 dB |

### Module W124: RIR/BRIR
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W124-01a | UF-W124-01 | anechoic scene | DRR > 40 dB | > 40 dB |
| UT-W124-01b | UF-W124-01 | same config × 2 runs | identical RIR | bit-identical |
| UT-W124-02a | UF-W124-02 | src at 90° az | ILD > 5 dB at 2 kHz | > 5 dB |
| UT-W124-02b | UF-W124-02 | src at 0° az | |ITD| < 50 µs | < 50 µs |
| UT-W124-03 | UF-W124-03 | alpha=0.0 | output = rir_start | RMS error < −80 dB |
| UT-W124-04 | UF-W124-04 | dynamic = static source | waveform match | RMS error < −80 dB |

### Module W143: Noise/Gain
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W143-01 | UF-W143-01 | signal at −20 dBFS, noise at −60 dBFS | SNR ∈ [38,42] dB | ±2 dB |
| UT-W143-03 | UF-W143-03 | signal peak +3 dBFS, clip=0 dBFS | clipped=True, n_clipped > 0 | always |

### Module W151: Configuration
| Test ID | UF | Input | Expected Output | Threshold |
|---------|-----|-------|-----------------|-----------|
| UT-W151-02a | UF-W151-02 | valid config YAML | SceneConfig object | no error |
| UT-W151-02b | UF-W151-02 | config missing 'room' field | ValidationError with 'room' in message | always |

---

## 3. Integration Test Plan (per IF chain)

### IT-W01. Scene Building Chain
**Chain:** IF-W111 → IF-W112 → IF-W113 → IF-W114 → IF-W115
**Test:** Build a complete shoebox scene with 2 sources, 4-mic ULA, concrete walls; serialize SceneState
**Pass Criteria:**
- SceneState.room.volume ∈ [10, 5000] m³
- SceneState.materials has entry for all surfaces
- All source/mic positions are inside room AABB
- SceneState serializes and deserializes identically

### IT-W02. RIR Generation Chain
**Chain:** IF-W121 → IF-W122 → IF-W123 → IF-W124
**Test:** Given SceneState (1 source, 1 mic, shoebox 5×4×3, concrete walls), generate full RIR
**Pass Criteria:**
- RT60 within ±15% of Sabine estimate for given absorption
- DRR > 0 dB (direct path stronger than average reverb)
- Peak at expected delay ± 1 sample
- Energy decays ≥ 60 dB from peak by RIR end

### IT-W03. Dynamic Rendering Chain
**Chain:** IF-W131 → IF-W133 → IF-W134
**Test:** Source moves linearly 2 m in 2 s; render at segment=20 ms
**Pass Criteria:**
- No click artifacts (energy discontinuity < −60 dB at any segment boundary)
- Output duration = trajectory duration ± 1 segment
- Static rendering of same scene (source at midpoint) matches dynamic at t=1 s within −30 dB RMS

### IT-W04. Device Chain
**Chain:** IF-W141 → IF-W142 → IF-W143 → IF-W144
**Test:** Apply full device chain to 4-channel rendered signal (speech at −20 dBFS)
**Pass Criteria:**
- Freq response within ±3 dB of specified mic response (100–8000 Hz)
- Array element positions perturbed within specified σ
- Output SNR matches target ± 3 dB
- Codec impairment tags written to metadata

### IT-W05. Batch + Manifest Chain
**Chain:** IF-W151 → IF-W152 → IF-W153
**Test:** Run batch of 10 scenes; verify manifest completeness
**Pass Criteria:**
- All 10 scene_manifest.json files exist
- All audio file paths in manifests are valid
- dataset_index.json contains 10 entries
- Re-running same configs produces identical manifests (seed reproducibility)

---

## 4. End-to-End Test Plan

### E2E-01. Single scene full pipeline
**Config:** shoebox 6×5×3 m, 2 speech sources (moving), 4-mic ULA, concrete+carpet, seed=42
**Pipeline:** config YAML → SceneValidation → SceneState → RIR generation → Dynamic rendering → Device chain → Manifest export
**Pass Criteria:**
- No errors or warnings in validation
- 2 output WAV files (stereo rendered + clean reference per source)
- RT60 in manifest within ±15% of Sabine prediction
- Re-run with seed=42 produces bit-identical WAV files (MD5 match)
- Total runtime < 30 s (single CPU core)

### E2E-02. Batch generation throughput
**Config:** 1000 scenes, 8-core CPU, Fs=16kHz, 2 sources, 4 mics, ISM order=3, 10 s duration
**Pass Criteria:**
- All 1000 scenes complete without silent failure
- Total elapsed time ≤ 3600 s
- Worker peak memory ≤ 4 GB each
- Log shows throughput ≥ 1000 scenes/hour

### E2E-03. Reproducibility across machines
**Config:** 50 scenes, seed=1–50, two different machines (same OS)
**Pass Criteria:**
- MD5 of all WAV files match between machines
- Note: IEEE 754 platform differences in ISM may cause 1-2 LSB differences — threshold relaxed to RMS error < −100 dB

### E2E-04. Edge-case robustness
**Configs:** anechoic room, max-reverb room (RT60=5 s), max sources (8), max mics (64), tiny room (2×2×2 m)
**Pass Criteria:**
- No uncaught exceptions
- All output WAVs non-empty
- RT60 within ±20% of target for extreme cases

---

## 5. Performance Benchmarks

| Benchmark | Target | Measurement Method |
|-----------|--------|--------------------|
| ISM RIR generation (Fs=16kHz, order=3) | ≥ 1000 RIRs/s per core | bench_rir_throughput.py |
| Full scene pipeline (10 s, 2 src, 4 mic) | < 5 s per scene on 1 core | bench_scene_pipeline.py |
| Batch 1000 scenes on 8 cores | < 3600 s | bench_batch_throughput.py |
| Config validation | < 10 ms | bench_config_validation.py |
| Visualization generation | < 5 s per scene | bench_visualization.py |
| Peak memory per worker | < 4 GB | memory_profiler on worker process |

---

## 6. Evidence Pack Structure

```
evidence_pack/
├── unit/
│   ├── test_room_geometry_results.xml       # pytest JUnit XML
│   ├── test_material_db_results.xml
│   ├── test_direct_path_results.xml
│   ├── test_rir_generation_results.xml
│   ├── test_occlusion_results.xml
│   ├── test_brir_results.xml
│   ├── test_dynamic_render_results.xml
│   ├── test_sensor_noise_results.xml
│   └── test_config_schema_results.xml
├── integration/
│   ├── it_scene_building_results.xml
│   ├── it_rir_chain_results.xml
│   ├── it_dynamic_render_results.xml
│   ├── it_device_chain_results.xml
│   └── it_batch_manifest_results.xml
├── e2e/
│   ├── e2e_single_scene_log.json
│   ├── e2e_batch_throughput_log.json
│   ├── e2e_reproducibility_hash_table.csv
│   └── e2e_edge_case_results.json
├── benchmarks/
│   ├── rir_throughput_bench.csv
│   ├── batch_runtime_log.json
│   └── memory_profile_report.html
├── plots/
│   ├── rt60_vs_sabine_scatter.png
│   ├── rir_energy_decay_sample.png
│   ├── binaural_ild_itd_table.png
│   ├── occlusion_vs_analytical.png
│   └── snr_distribution.png
└── coverage/
    ├── unit_coverage.html           # pytest-cov HTML report
    └── coverage_summary.json        # {line_coverage: %, branch_coverage: %}
```

---

## 7. Regression Thresholds

| Metric | Green (pass) | Yellow (investigate) | Red (block release) |
|--------|-------------|---------------------|---------------------|
| Unit test pass rate | 100% | 99–100% | < 99% |
| RT60 accuracy vs. Sabine | < ±10% | ±10–15% | > ±15% |
| RIR throughput | ≥ 1000/s | 800–1000/s | < 800/s |
| Batch throughput | ≥ 1000 scenes/hr | 800–1000/hr | < 800/hr |
| Bit-identical reproduction | MD5 match | — | any MD5 mismatch |
| E2E pipeline without error | 100% | 98–100% | < 98% |
| Line coverage | ≥ 90% | 85–90% | < 85% |
