# W300000. Synthetic-to-Real Gap Reduction Training Strategy Design

## 1. Objective
Design and implement learning strategies that reduce the performance gap between synthetic training conditions and real deployment conditions.

---

## 2. Requirement Summary
The training system shall:
- support synthetic-only, real-only, and mixed-data training modes,
- calibrate simulator parameters using real observations,
- improve robustness to device, room, and environmental mismatch,
- support self-supervised, supervised, and adaptation-based training,
- provide evidence that gap reduction improves real-world downstream performance.

---

## 3. Integrated Capability Derivation

### IC-W3-01. Data-aware training orchestration
The system shall compose synthetic and real datasets into controlled training curricula.

### IC-W3-02. Domain gap analysis and calibration
The system shall estimate mismatch factors and feed corrections back to data generation or training.

### IC-W3-03. Robust and adaptive model learning
The system shall train models that generalize across unseen rooms, devices, and acoustic conditions.

### IC-W3-04. Gap-reduction evaluation loop
The system shall measure synthetic-real mismatch and iteratively reduce it.

---

## 4. Integrated Capability Decomposition

## W310000. Training data composition and curriculum
### W311000. Synthetic-real dataset blending
### W312000. Curriculum and difficulty scheduling
### W313000. Task-conditioned batching
### W314000. Experiment configuration management

## W320000. Gap analysis and simulator calibration
### W321000. Real-data acoustic profile estimation
### W322000. Device/channel mismatch estimation
### W323000. Simulator parameter calibration loop
### W324000. Domain gap metric computation

## W330000. Robust learning and domain adaptation
### W331000. Separation model baseline training
### W332000. Self-supervised or representation pretraining
### W333000. Domain adaptation / invariant feature learning
### W334000. Robustness augmentation and regularization

## W340000. Iterative improvement and model governance
### W341000. Ablation and factor attribution
### W342000. Real-world validation loop
### W343000. Model selection and regression control
### W344000. Deployment profile export

---

## 5. Unit Function Derivation

## W311000. Synthetic-real dataset blending
- **UF-W311-01**: Register synthetic and real dataset sources
- **UF-W311-02**: Define sampling weights by data domain
- **UF-W311-03**: Mix labeled and unlabeled real data streams
- **UF-W311-04**: Record domain composition per experiment

## W312000. Curriculum and difficulty scheduling
- **UF-W312-01**: Start from easier synthetic conditions
- **UF-W312-02**: Increase reverberation/noise/motion difficulty over time
- **UF-W312-03**: Inject real data according to stage schedule
- **UF-W312-04**: Freeze or adapt curriculum based on validation gap

## W313000. Task-conditioned batching
- **UF-W313-01**: Build batch samplers by task target (separation/ASR/diar/localization)
- **UF-W313-02**: Support multi-task paired labels in same batch
- **UF-W313-03**: Enforce domain diversity within batch
- **UF-W313-04**: Export batch composition stats

## W314000. Experiment configuration management
- **UF-W314-01**: Define experiment YAML schema
- **UF-W314-02**: Track seeds, datasets, model, loss, and scheduler config
- **UF-W314-03**: Resume/reproduce experiments exactly
- **UF-W314-04**: Link experiment to dataset/model/eval versions

## W321000. Real-data acoustic profile estimation
- **UF-W321-01**: Estimate reverberation-related statistics from real recordings
- **UF-W321-02**: Estimate noise class and stationarity characteristics
- **UF-W321-03**: Estimate overlap and speaker-count distributions
- **UF-W321-04**: Summarize real-domain acoustic profile report

## W322000. Device/channel mismatch estimation
- **UF-W322-01**: Estimate channel response differences across devices
- **UF-W322-02**: Estimate bandwidth/compression artifact patterns
- **UF-W322-03**: Estimate array geometry uncertainty from recordings if possible
- **UF-W322-04**: Convert mismatch estimates into simulator/training parameters

## W323000. Simulator parameter calibration loop
- **UF-W323-01**: Compare synthetic statistics against real statistics
- **UF-W323-02**: Optimize simulator parameter ranges to reduce mismatch
- **UF-W323-03**: Generate corrected synthetic batches
- **UF-W323-04**: Record calibration history and improvement trend

## W324000. Domain gap metric computation
- **UF-W324-01**: Compute feature-space distance between synthetic and real data
- **UF-W324-02**: Compute performance gap by domain split
- **UF-W324-03**: Score per-factor gap contribution (room/device/noise/motion)
- **UF-W324-04**: Produce domain-gap dashboard

## W331000. Separation model baseline training
- **UF-W331-01**: Train supervised separation baseline on synthetic data
- **UF-W331-02**: Support single-channel and multi-channel variants
- **UF-W331-03**: Support mask-based, waveform-based, or hybrid objectives
- **UF-W331-04**: Export checkpoints and baseline metrics

## W332000. Self-supervised or representation pretraining
- **UF-W332-01**: Pretrain encoder on synthetic + real mixtures
- **UF-W332-02**: Use spatial/audio consistency objectives
- **UF-W332-03**: Transfer pretrained encoder to downstream models
- **UF-W332-04**: Compare pretrained vs non-pretrained baselines

## W333000. Domain adaptation / invariant feature learning
- **UF-W333-01**: Apply adversarial or discrepancy-based domain adaptation
- **UF-W333-02**: Learn domain-invariant latent representations
- **UF-W333-03**: Fine-tune with small labeled real dataset if available
- **UF-W333-04**: Evaluate adaptation benefit on unseen real conditions

## W334000. Robustness augmentation and regularization
- **UF-W334-01**: Apply device/noise/reverb/channel augmentation
- **UF-W334-02**: Apply consistency regularization across rendered variants
- **UF-W334-03**: Apply hard-negative or confusing-condition mining
- **UF-W334-04**: Measure robustness gain by stress-test set

## W341000. Ablation and factor attribution
- **UF-W341-01**: Remove one realism factor at a time
- **UF-W341-02**: Remove one adaptation strategy at a time
- **UF-W341-03**: Estimate factor contribution to real-world gain
- **UF-W341-04**: Generate ablation summary tables

## W342000. Real-world validation loop
- **UF-W342-01**: Evaluate on held-out real recordings
- **UF-W342-02**: Collect failure cases by acoustic condition
- **UF-W342-03**: Feed failure profile back to simulator and curriculum
- **UF-W342-04**: Track iteration-to-iteration real-world improvement

## W343000. Model selection and regression control
- **UF-W343-01**: Select best model by weighted multi-metric criteria
- **UF-W343-02**: Detect regression on real benchmark suite
- **UF-W343-03**: Freeze release candidates with reproducible config
- **UF-W343-04**: Archive rejected runs with reason codes

## W344000. Deployment profile export
- **UF-W344-01**: Export model variants by latency/quality tier
- **UF-W344-02**: Export inference preprocessing configuration
- **UF-W344-03**: Export expected operating condition profile
- **UF-W344-04**: Package model card with domain-gap notes

---

## 6. Interfaces and Outputs
- Training configs and experiment manifests
- Calibrated simulator parameter sets
- Baseline/adapted model checkpoints
- Domain gap dashboards and ablation reports
- Deployment-ready model profiles

---

## 7. Verification Focus
- Reduction of performance gap on real data
- Stability across devices and acoustic environments
- Explainability of what reduced the gap
- Reproducibility of adaptation experiments
- No hidden regression in downstream use cases
