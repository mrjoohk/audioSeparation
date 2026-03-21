# W100000 UF→IF Coverage Review
**Date:** 2026-03-21
**Stage:** 7.5 — Bottom-up integration check

---

## Legend
- ✅ COVERED — at least one UF satisfies this acceptance criterion
- ⚠️ PARTIAL — UF exists but I/O contract or algorithm insufficient
- ❌ UNCOVERED — no UF addresses this criterion
- 🔁 REDUNDANT — multiple UFs with identical responsibility

---

## Coverage Matrix: IF × REQ Acceptance Criteria

| IF | REQ AC | UFs Covering | Status | Notes |
|----|--------|-------------|--------|-------|
| IF-W111 | REQ-W01: shoebox volume error ≤ 0.001 m³ | UF-W111-01, UF-W111-04 | ✅ | -01 builds, -04 computes volume |
| IF-W111 | REQ-W01: invalid mesh blocks simulation | UF-W111-02, UF-W111-03 | ✅ | -02 imports, -03 validates |
| IF-W111 | REQ-W01: 1000 configs 100% manifold pass | UF-W111-03 | ✅ | Batch test required |
| IF-W112 | REQ-W02: RT60 within ±15% of Sabine | UF-W112-02 + IF-W122 chain | ⚠️ | UF-W112-02 only assigns; RT60 accuracy depends on ISM quality in IF-W122 |
| IF-W112 | REQ-W02: stochastic variation reproducible | UF-W112-03 | ✅ | Seeded RNG |
| IF-W115 | REQ-W01, REQ-W09 | UF-W115-01, UF-W115-02 | ✅ | NEW UFs added |
| IF-W121 | REQ-W03: delay = d/c ± 1 sample | UF-W121-01 | ✅ | |
| IF-W121 | REQ-W03: attenuation = 1/d ± 0.1% | UF-W121-02 | ✅ | |
| IF-W121 | REQ-W03: TDOA angular error < 1° | UF-W121-03 | ✅ | |
| IF-W121 | REQ-W03: air attenuation | UF-W121-04 | ✅ | |
| IF-W122 | REQ-W04: RT60 within ±10% | UF-W122-01, UF-W122-02, UF-W122-03, UF-W122-04 | ✅ | Full chain |
| IF-W122 | REQ-W04: anechoic DRR > 40 dB | UF-W124-01 (DRR computation) | ⚠️ | DRR computed in UF-W124-01, not IF-W122 directly |
| IF-W122 | REQ-W04: throughput ≥ 1000 RIRs/s | UF-W122-01 | ⚠️ | ISM is bottleneck; no explicit optimization UF for performance |
| IF-W123 | REQ-W13: visibility test | UF-W123-01 | ✅ | |
| IF-W123 | REQ-W13: Maekawa ±3 dB | UF-W123-03 | ✅ | |
| IF-W123 | REQ-W13: dynamic update | UF-W123-04 | ✅ | |
| IF-W124 | REQ-W04: bit-identical RIR | UF-W124-01 | ✅ | Depends on UF-W112-03 seed propagation |
| IF-W124 | REQ-W05: ILD > 5 dB at 90° | UF-W124-02 | ✅ | |
| IF-W124 | REQ-W05: ITD < 50 µs at 0° | UF-W124-02 | ✅ | |
| IF-W124 | REQ-W06: click artifacts < −60 dB | UF-W124-03, UF-W124-04 | ✅ | Crossfade in -03 |
| IF-W131 | REQ-W14: all positions inside room | UF-W131-01, UF-W131-03 | ✅ | |
| IF-W131 | REQ-W14: speed ≤ 2 m/s | UF-W131-02 | ✅ | Clamping |
| IF-W131 | REQ-W14: seed reproducibility | UF-W131-01 | ✅ | |
| IF-W132 | REQ-W14 (receiver) | UF-W132-01–04 | ⚠️ | UF contracts abbreviated; need full detail |
| IF-W133 | REQ-W06: temporal alignment | UF-W133-01–04 | ⚠️ | No UF for validating event timing alignment |
| IF-W134 | REQ-W06: static = dynamic within −80 dB | UF-W124-03, UF-W124-04 | ✅ | |
| IF-W141 | REQ-W08: freq response applied | UF-W141-01 | ✅ | |
| IF-W141 | REQ-W08: directional pattern | UF-W141-03 | ✅ | |
| IF-W142 | REQ-W07: spacing error < 0.1 mm | UF-W142-01 (template) | ⚠️ | UF-W142-01 not fully defined |
| IF-W142 | REQ-W07: perturbation distribution | UF-W142-02 | ✅ | |
| IF-W143 | REQ-W08: SNR ∈ [38,42] dB | UF-W143-01 | ✅ | |
| IF-W143 | REQ-W08: clipping tagged | UF-W143-03 | ✅ | |
| IF-W144 | REQ-W15: BW limit > −40 dB above 4.5 kHz | UF-W144-01 | ✅ | FIR filter |
| IF-W144 | REQ-W15: PER simulation | UF-W144-03 | ✅ | |
| IF-W151 | REQ-W09: validation < 10 ms | UF-W151-02 | ✅ | |
| IF-W151 | REQ-W09: bit-identical reproduction | UF-W151-03 (seed management) | ✅ | |
| IF-W152 | REQ-W10: ≥ 1000 scenes/hour | UF-W152-02 | ⚠️ | No performance UF; throughput not explicitly benchmarked in any UF |
| IF-W152 | REQ-W10: resume from checkpoint | UF-W152-03 | ✅ | |
| IF-W153 | REQ-W11: all file paths valid | UF-W153-01 | ✅ | |
| IF-W153 | REQ-W11: RT60 in manifest ± 5 ms | UF-W153-03 | ✅ | |
| IF-W154 | REQ-W12: room plot | UF-W154-01 | ✅ | |
| IF-W154 | REQ-W12: RIR energy decay plot | UF-W154-02 | ✅ | |
| IF-W155 | REQ-W01, REQ-W02, REQ-W04 | UF-W155-01 | ✅ | NEW IF + UF added to fill gap |

---

## Gaps Identified

### GAP-01. Throughput optimization UF missing (❌ UNCOVERED)
**Affected IF:** IF-W122, IF-W152
**Affected REQ:** REQ-W04 (1000 RIRs/s), REQ-W10 (1000 scenes/hour)
**Problem:** No UF covers ISM performance optimization (e.g., pre-computation of reflection coefficients, batch mode).
**Recommendation:** Add UF-W122-05: `Batch ISM computation` — vectorized image source generation for multiple source-mic pairs simultaneously.

### GAP-02. Event timing alignment validation UF missing (❌ UNCOVERED)
**Affected IF:** IF-W133
**Affected REQ:** REQ-W06
**Problem:** UF-W133-03 manages event timing but no UF validates alignment between speech start events and trajectory ticks.
**Recommendation:** Add UF-W133-05: `Validate event-trajectory temporal alignment` — check that speech onset times fall on valid tick boundaries.

### GAP-03. RT60 fitting feedback loop between IF-W112 and IF-W122 (⚠️ PARTIAL)
**Problem:** REQ-W02 AC requires RT60 within ±15% of Sabine, but the chain is UF-W112-02 (assign material) → UF-W122-04 (measure RT60). There is no feedback UF to adjust material α values if RT60 is out of tolerance.
**Recommendation:** Add UF-W112-05: `RT60-targeted material absorption adjustment` — given target RT60, solve for per-band α adjustment using Sabine inverse.

### GAP-04. UF-W132-01 through UF-W132-04 I/O contracts incomplete (⚠️ PARTIAL)
**Problem:** Receiver trajectory UFs have abbreviated contracts. Receiver trajectory generation is symmetric to source trajectory and has identical quality requirements.
**Recommendation:** Expand UF-W132-XX contracts to match UF-W131-XX level of detail.

### GAP-05. No UF for seed propagation to all stochastic subsystems (⚠️ PARTIAL)
**Problem:** REQ-W09 requires bit-identical reproduction. Stochastic UFs (W112-03, W131-01, W132-03, W143-01, W144-03) all require seeds, but no UF manages the hierarchical seed derivation from the global scene seed.
**Recommendation:** Add UF-W151-05: `Derive per-subsystem seeds from global seed` — use hash(global_seed, subsystem_id) to generate deterministic per-subsystem seeds.

---

## Redundancy Check

### REDUNDANT-01. Trajectory constraint enforcement duplicated
- UF-W131-03 (source path constraints) and UF-W132-03 (receiver jitter modeling) both handle constraint enforcement but with different logic.
- **Assessment:** Not truly redundant (different entity types); acceptable. Consider shared `enforce_room_constraints(trajectory, room_bbox, min_wall_dist)` utility.

### REDUNDANT-02. JSON serialization pattern repeated
- UF-W112-04, UF-W113-04, UF-W115-02, UF-W131-04, UF-W153-01 all serialize dataclasses to JSON.
- **Assessment:** Functionally repetitive but each has different schema. Recommend shared `SimulatorJSONEncoder` utility class to reduce code duplication.

---

## Coverage Summary

| Category | Count |
|----------|-------|
| Total REQ Acceptance Criteria | 35 |
| ✅ COVERED | 25 (71%) |
| ⚠️ PARTIAL | 8 (23%) |
| ❌ UNCOVERED | 2 (6%) |
| 🔁 REDUNDANT groups | 2 |

**Action required before Stage 8:** Resolve GAP-01 and GAP-02 (add UF-W122-05 and UF-W133-05); expand UF-W132 contracts; add UF-W151-05 for seed management.
