# W100000 Spatial Simulator — Design Analysis Report
**Date:** 2026-03-21
**Base Document:** W100000_Spatial_Simulator_Design.md
**Reviewer Process:** Core Engineering Stages 1–8

---

## 1. Gap Analysis Against Core Engineering Stages

| Stage | Name | Status | Gap Description |
|-------|------|--------|-----------------|
| 1 | Problem Definition | PARTIAL | Objective present but no explicit scope-of-impact, stakeholder list, or timeline |
| 2 | Problem Review & Clarification | MISSING | No clarification log; ambiguous terms undefined |
| 3 | Constraints / Assumptions | MISSING | No sample rate, latency, memory, or accuracy bounds specified |
| 4 | Requirements Elicitation (REQ Blocks) | PARTIAL | Bullet list only; no acceptance criteria, no numeric thresholds, no I/O specs |
| 5 | IF Identification | PARTIAL | IC-W1-0X blocks present but lack interface specs (inputs/outputs/constraints/linked REQs) |
| 6 | IF Decomposition | PARTIAL | W110000–W154000 hierarchy exists but no dependency graph, no SRP validation |
| 7 | UF Definition (UF Blocks) | PARTIAL | UF names listed; all I/O contracts, algorithm summaries, edge cases, verification plans missing |
| 7.5 | UF→IF Coverage Review | MISSING | No coverage matrix; no UNCOVERED/REDUNDANT analysis |
| 8 | Verification & Evidence Planning | PARTIAL | "Verification Focus" bullet list only; no test plans, no thresholds, no evidence pack |

**Score: 3/9 stages adequately defined**

---

## 2. Critical Problems Found

### P-01. No Numeric Acceptance Criteria (Severity: CRITICAL)
**Problem:** Section 2 uses qualitative bullets ("simulate propagation, reflection, absorption").
No requirement states a testable number (e.g., RT60 error < X%, RIR length ≥ Y ms, SNR range Z dB).
**Impact:** Impossible to verify whether the simulator meets requirements. Any implementation will "pass" by default.
**Fix:** Rewrite all requirements as REQ blocks with Given/When/Then + numeric thresholds (see `requirements.md`).

### P-02. All UF Blocks Missing I/O Contracts (Severity: CRITICAL)
**Problem:** 44 UFs listed as one-liner descriptions. Zero have typed inputs/outputs, units, or tensor shapes.
Example: `UF-W121-01: Compute source-to-mic distance and delay` — no specification of:
- Input: source position (3D float, meters, world frame), mic position (3D float, meters)
- Output: distance (float, meters), delay (float, seconds)

**Impact:** Developers cannot implement without re-inferring the contract. Integration testing is impossible.
**Fix:** Add I/O contracts for all UFs (see `uf.md`).

### P-03. Missing Physical/System Constraints (Severity: HIGH)
**Problem:** No operating envelope is defined:
- Audio sample rate (8kHz? 16kHz? 48kHz?)
- Maximum room dimensions (2m×2m? 100m×100m?)
- Maximum number of sources/mics per scene
- RIR maximum length (ms or samples)
- Real-time vs. offline processing distinction
- Platform/memory budget

**Impact:** Cannot bound algorithm complexity or validate feasibility.
**Fix:** Add `assumptions_and_constraints.md`.

### P-04. Naming/Hierarchy Inconsistency (Severity: HIGH)
**Problem:** Three naming systems coexist without clear mapping:
1. `IC-W1-0X` — 5 Integrated Capabilities (Section 3)
2. `W1X0000` — 20 intermediate modules (Section 4)
3. `UF-W1XX-0X` — 44 Unit Functions (Section 5)

IC-W1-01 "3D acoustic scene definition" maps to W110000–W114000 (4 modules, 16 UFs).
IC-W1-02 "Acoustic propagation" maps to W120000–W124000 (4 modules, 16 UFs).
But there is **no explicit mapping table** and IC ≠ IF in core-engineering terminology.
**Fix:** Establish 3-level hierarchy: **IC → IF (W1X0000 level) → UF (UF-W1XX-0X level)** with explicit parent→child tables.

### P-05. No Data Flow / Pipeline Specification (Severity: HIGH)
**Problem:** The document defines components but not how data flows between them.
- What does W121000 output that W124000 consumes?
- How does W151000 (job config) pass parameters to W111000 (room geometry)?
- What is the data contract between W130000 (motion) and W120000 (propagation)?

**Impact:** Integration work will discover interface mismatches at late stages.
**Fix:** Add data flow diagram and inter-IF interface table in `if_list.md`.

### P-06. No Dynamic Scene Timing Model (Severity: MEDIUM)
**Problem:** W130000 (Dynamic motion) lacks:
- Update rate specification (Hz)
- Minimum segment length for dynamic convolution
- Latency vs. accuracy trade-off policy

UF-W133-01 says "synchronize by simulation tick" but tick duration is undefined.
**Fix:** Add W133000 timing contract with explicit tick rate and interpolation policy.

### P-07. Occlusion/Diffraction Model Underspecified (Severity: MEDIUM)
**Problem:** W123000 only says "approximation" with no method specified:
- Geometric acoustics vs. wave-based?
- Which diffraction model (Keller, Maekawa, UTD)?
- Under what conditions is occlusion applied (threshold distance, angle)?

**Fix:** Specify approximation method and validity conditions in W123000 UF contracts.

### P-08. No Binaural/HRTF Model Specification (Severity: MEDIUM)
**Problem:** UF-W124-02 mentions BRIR output but no HRTF database or interpolation method is specified:
- Which HRTF dataset (CIPIC, KEMAR, MIT)?
- Angular resolution for interpolation?
- Subject variability handling?

**Fix:** Add HRTF source and interpolation contract to W124000.

---

## 3. Design Improvement Recommendations

### R-01. Establish a 3-Level Hierarchy with Explicit Mapping
```
Level 0: System — W100000 (Spatial Simulator)
Level 1: IC (Integrated Capability) — IC-W1-01 through IC-W1-05
Level 2: IF (Integration Function) — W111000 through W154000 (20 IFs)
Level 3: UF (Unit Function)        — UF-W111-01 through UF-W154-04 (44 UFs)
```
Each IC owns a set of IFs; each IF owns a set of UFs. Parent links must be explicit.

### R-02. Add Missing IFs for Cross-Cutting Concerns
Current design has no IF for:
- **W160000. Scene validation pipeline** — validates geometry + acoustic plausibility before rendering
- **W170000. Reproducibility control** — seed management, version locking, config hash
- **W180000. Performance monitoring** — render time tracking, memory profiling

These are implied by UF-W151-03, UF-W154-04, etc., but have no owning IF.

### R-03. Separate "Scene Builder" from "Renderer"
Current W110000–W113000 mix static scene definition with runtime state.
Recommended split:
- **W110000. Scene Definition** (static: geometry + materials + objects) → serializable, seed-reproducible
- **W115000. Scene State Manager** (runtime: world transform graph, active trajectories, tick state)

This separation enables scene caching, parallelism, and cleaner testing.

### R-04. Define a Canonical Scene State Object
All IFs should share a well-typed `SceneState` object:
```
SceneState {
  tick_id: int
  room: RoomGeometry
  sources: List[SourceState]  # position, velocity, active_signal_ref
  receivers: List[ReceiverState]  # position, orientation, array_config
  materials: MaterialMap
  obstacles: List[ObstacleState]
}
```
This makes inter-IF contracts unambiguous.

### R-05. Add Acoustic Plausibility Validation UFs
Missing validation functions:
- Verify RT60 within physically realizable bounds for given room volume/absorption
- Verify DRR is consistent with source-mic distance
- Verify RIR energy decay is monotonic

These are critical for dataset quality but absent from W154000.

### R-06. Specify Batch Parallelism Architecture
W152000 says "parallelize scene rendering" but no model is specified:
- Process-based (multiprocessing) vs. thread-based vs. GPU-accelerated?
- How are random seeds assigned across workers?
- What is the failure/retry strategy per job?

Recommend adding W152000 UFs for: worker pool config, seed assignment policy, partial-failure recovery.

### R-07. Add Downstream Dataset Interface Contract
Section 6 lists "manifest for downstream dataset builder" but no schema is defined.
Recommend: add `W153000` UF for manifest schema (JSON-LD or HDF5 index) with explicit fields:
- scene_id, source_ids, mic_ids, audio_paths, rir_paths, metadata_path, acoustic_summary

---

## 4. Summary: Recommended Output Artifacts to Generate

| Artifact | Status | Action |
|----------|--------|--------|
| `clarification_log.md` | MISSING | Create — resolve 8 ambiguous terms |
| `assumptions_and_constraints.md` | MISSING | Create — enumerate all physical/system bounds |
| `requirements.md` | INCOMPLETE | Rewrite as 15 REQ blocks with numeric AC |
| `if_list.md` | INCOMPLETE | Rewrite — 22 IFs with I/O specs and linked REQs |
| `if_decomposition.md` | MISSING | Create — dependency graph per IF |
| `uf.md` | INCOMPLETE | Extend all 44 UFs with I/O contracts + edge cases |
| `uf_if_coverage_review.md` | MISSING | Create — 22×44 coverage matrix |
| `verification_plan.md` | INCOMPLETE | Rewrite — test plans per UF/IF/E2E with thresholds |
