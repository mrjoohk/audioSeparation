# W200000. Dynamic and Realistic Training Data Generation Design

## 1. Objective
Use the simulator to generate large-scale synthetic training data that is dynamic, varied, realistic, well-labeled, and directly consumable by speech separation and downstream learning pipelines.

---

## 2. Requirement Summary
The data generation system shall:
- create diverse acoustic scenarios at scale,
- combine clean speech, noise, interferers, and events,
- support dynamic scenes and variable task difficulty,
- generate synchronized labels and manifests,
- manage dataset versioning, partitioning, and quality control.

---

## 3. Integrated Capability Derivation

### IC-W2-01. Scenario synthesis factory
The system shall generate scenario definitions covering rooms, speakers, devices, motion, and acoustic conditions.

### IC-W2-02. Audio asset assembly and rendering pipeline
The system shall combine source assets with simulated acoustics to produce task-ready mixtures and references.

### IC-W2-03. Label and metadata generation
The system shall create rich labels for separation, diarization, localization, and ASR-aligned use.

### IC-W2-04. Dataset operations and quality management
The system shall version, validate, partition, and publish datasets with reproducibility.

---

## 4. Integrated Capability Decomposition

## W210000. Scenario planning and sampling
### W211000. Scenario ontology and parameter space
### W212000. Sampling strategy and coverage control
### W213000. Difficulty control and curriculum tiers
### W214000. Scenario manifest generation

## W220000. Source and event composition
### W221000. Clean speech asset ingestion
### W222000. Noise/interference asset ingestion
### W223000. Multi-speaker overlap composition
### W224000. Dynamic event scheduling

## W230000. Rendering and data packaging
### W231000. Mixture rendering orchestration
### W232000. Clean reference generation
### W233000. Label generation and synchronization
### W234000. Dataset packaging and storage

## W240000. Dataset quality and lifecycle management
### W241000. Automated QC checks
### W242000. Train/val/test partition control
### W243000. Dataset versioning and lineage
### W244000. Statistics dashboard and balancing

---

## 5. Unit Function Derivation

## W211000. Scenario ontology and parameter space
- **UF-W211-01**: Define parameter schema for room/source/mic/device/noise/motion
- **UF-W211-02**: Define scenario classes (meeting, home, vehicle, public, wearable, robot)
- **UF-W211-03**: Define allowed parameter ranges and constraints
- **UF-W211-04**: Tag scenarios by intended task and difficulty

## W212000. Sampling strategy and coverage control
- **UF-W212-01**: Randomly sample within constrained parameter ranges
- **UF-W212-02**: Perform stratified coverage over key realism factors
- **UF-W212-03**: Track under-covered parameter regions
- **UF-W212-04**: Re-sample to balance dataset coverage

## W213000. Difficulty control and curriculum tiers
- **UF-W213-01**: Score scenario difficulty from overlap, reverberation, motion, and noise
- **UF-W213-02**: Generate tiered subsets (easy/medium/hard/extreme)
- **UF-W213-03**: Enforce target counts per tier
- **UF-W213-04**: Export curriculum-ready split definitions

## W214000. Scenario manifest generation
- **UF-W214-01**: Create per-sample manifest with deterministic seed
- **UF-W214-02**: Bind selected assets to scenario parameters
- **UF-W214-03**: Record provenance of all inputs
- **UF-W214-04**: Store manifest for replay/regeneration

## W221000. Clean speech asset ingestion
- **UF-W221-01**: Import speech corpora and normalize format
- **UF-W221-02**: Segment utterances and detect silence boundaries
- **UF-W221-03**: Attach speaker/language/domain metadata
- **UF-W221-04**: Filter low-quality or clipped assets

## W222000. Noise/interference asset ingestion
- **UF-W222-01**: Import background noise/event collections
- **UF-W222-02**: Tag assets by environment and stationarity
- **UF-W222-03**: Normalize and segment event assets
- **UF-W222-04**: Build retrieval index for scenario-conditioned noise selection

## W223000. Multi-speaker overlap composition
- **UF-W223-01**: Select speaker combinations by target overlap ratio
- **UF-W223-02**: Control turn-taking vs true overlap patterns
- **UF-W223-03**: Apply class balance for speaker count and gender/language if needed
- **UF-W223-04**: Generate clean reference stems for each speaker

## W224000. Dynamic event scheduling
- **UF-W224-01**: Schedule speech start/stop and interruption events
- **UF-W224-02**: Schedule motion changes and pose transitions
- **UF-W224-03**: Schedule transient noise events and distractors
- **UF-W224-04**: Export unified event timeline

## W231000. Mixture rendering orchestration
- **UF-W231-01**: Submit manifests to simulator backend
- **UF-W231-02**: Render multichannel mixtures
- **UF-W231-03**: Render condition-specific variants of same scenario
- **UF-W231-04**: Capture logs and failure reasons

## W232000. Clean reference generation
- **UF-W232-01**: Render anechoic or minimally processed target references
- **UF-W232-02**: Render per-speaker spatialized clean references if needed
- **UF-W232-03**: Export noise-only and interference-only references
- **UF-W232-04**: Align all references sample-accurately with mixtures

## W233000. Label generation and synchronization
- **UF-W233-01**: Generate speech activity and overlap labels
- **UF-W233-02**: Generate speaker identity/session labels
- **UF-W233-03**: Generate localization labels (position, DOA, trajectory)
- **UF-W233-04**: Generate transcript/time alignment links when source text exists

## W234000. Dataset packaging and storage
- **UF-W234-01**: Package audio and labels into dataset directory structure
- **UF-W234-02**: Generate manifest index and checksum list
- **UF-W234-03**: Compress or shard large datasets
- **UF-W234-04**: Publish dataset card and schema documentation

## W241000. Automated QC checks
- **UF-W241-01**: Detect silent/corrupted files
- **UF-W241-02**: Validate label-audio alignment
- **UF-W241-03**: Validate amplitude/clipping/SNR range
- **UF-W241-04**: Flag duplicate or near-duplicate samples

## W242000. Train/val/test partition control
- **UF-W242-01**: Split by speaker leakage constraints
- **UF-W242-02**: Split by room/device/scenario leakage constraints
- **UF-W242-03**: Support challenge-style unseen-condition test splits
- **UF-W242-04**: Freeze split definitions by dataset version

## W243000. Dataset versioning and lineage
- **UF-W243-01**: Assign dataset semantic version
- **UF-W243-02**: Link version to simulator/config/code revision
- **UF-W243-03**: Track regenerated samples and deltas
- **UF-W243-04**: Maintain lineage record for reproducibility

## W244000. Statistics dashboard and balancing
- **UF-W244-01**: Summarize room/noise/motion/device distributions
- **UF-W244-02**: Summarize task difficulty distribution
- **UF-W244-03**: Highlight imbalance and missing coverage
- **UF-W244-04**: Recommend next data generation batch targets

---

## 6. Interfaces and Outputs
- Synthetic mixture waveforms
- Clean source stems
- SAD/overlap/trajectory/DOA/transcript-aligned labels
- Scenario manifests and dataset cards
- Dataset statistics and QC reports

---

## 7. Verification Focus
- Coverage of intended parameter space
- Realism and diversity of generated scenarios
- Accuracy and completeness of labels
- Reproducibility of dataset builds
- Leakage-free evaluation splits
