# 3D Audio Simulation → Data Generation → Domain Gap Reduction → Downstream Proof

## 1. Purpose
This document organizes the proposed program into four top-level WBS items and expands each item using the following design logic:

1. Derive **integrated capabilities** from goals and requirements
2. Perform **integrated capability decomposition**
3. Derive **unit functions** that are implementable and testable

The objective is to build a full pipeline that:
- constructs a 3D/room/spatial audio simulator,
- generates dynamic and realistic training data at scale,
- reduces the synthetic-to-real gap during model training,
- proves gains not only in separation quality but also in ASR, diarization, and localization.

---

## 2. Top-Level WBS Structure

- **W100000. 3D/room/spatial simulator construction**
- **W200000. Large-scale generation of dynamic and realistic training data**
- **W300000. Training strategy design for reducing synthetic-to-real gap**
- **W400000. Proof of improvement in separation + ASR/diarization/localization**

---

## 3. End-to-End Integrated Capabilities

### IC-01. Physically grounded 3D audio scene simulation
A system shall simulate acoustic scenes with room geometry, source/microphone placement, motion, propagation, reflection, absorption, and sensor characteristics.

### IC-02. Scalable data generation and labeling pipeline
A system shall generate large volumes of synthetic mixtures, clean references, spatial labels, metadata, and scenario manifests.

### IC-03. Domain-gap-aware model training pipeline
A system shall train separation and related models using synthetic and real data together, with calibration, adaptation, and robustness strategies.

### IC-04. Downstream task validation and operational proof
A system shall demonstrate measurable improvement in downstream tasks such as ASR, diarization, and localization under controlled and realistic conditions.

---

## 4. Cross-WBS Architecture View

### Layer A. World and acoustic simulation
Mapped mainly to **W100000**

### Layer B. Scenario synthesis and dataset factory
Mapped mainly to **W200000**

### Layer C. Model training and domain adaptation
Mapped mainly to **W300000**

### Layer D. Evaluation, benchmarking, and operational validation
Mapped mainly to **W400000**

---

## 5. Recommended Development Sequence

### Phase 1. Simulator baseline
- Static room geometry
- Static sources and microphones
- Basic RIR/BRIR generation
- Single-task speech separation baseline

### Phase 2. Dynamic scene generation
- Moving sources/microphones
- Noise/event injection
- Large-scale batch generation
- Rich metadata and label packaging

### Phase 3. Gap reduction
- Device/channel mismatch modeling
- Synthetic-real mixed training
- Domain randomization and curriculum
- Real-data calibration loop

### Phase 4. Downstream proof
- Separation + ASR + diarization + localization benchmarks
- Ablation by realism factor
- Deployment-oriented evaluation

---

## 6. File Map

- `W100000_Spatial_Simulator_Design.md`
- `W200000_Synthetic_Data_Generation_Design.md`
- `W300000_Synthetic_to_Real_Training_Design.md`
- `W400000_Downstream_Validation_Design.md`

Each file expands one top-level WBS item in the form:
- integrated capability derivation,
- decomposition,
- unit functions,
- interfaces and outputs,
- verification focus.
