# Stage 4: Requirements (W300000 Synthetic-to-Real Training)

## Overview
This document specifies the software requirements for the W300000 Synthetic-to-Real gap reduction training strategy system, adhering to the core-engineering 8-stage design process. The requirements are transformed from the initial high-level objectives in `W300000_Synthetic_to_Real_Training_Design.md` (§2).

---

## REQ-301: Mixed-Data Curriculum Training orchestration
- **ID:** REQ-301
- **Context:** 단일 데이터 소스에 편향되지 않도록 합성 데이터 전용, 리얼 데이터 전용, 그리고 혼합 스트림 학습 모드를 지원하고 커리큘럼 기반 난이도 조절을 수행해야 함.
- **Inputs:** 
  - Iteration step $T$
  - Synthetic mini-batch (audio tensors & labels)
  - Real mini-batch (audio tensors & partial/pseudo labels)
- **Outputs:** Model parameter gradients $\nabla \theta$ corresponding to the mixed-batch loss.
- **Constraints:** 학습 파이프라인 상에서 두 데이터 소스를 믹스할 때, I/O 병목(IO bottleneck)이 전체 스텝 속도를 10% 이상 저하시키지 않아야 함.
- **Acceptance Criteria:**
  - given "50% Synthetic / 50% Real 샘플링 가중치가 설정된 학습 단계"
  - when "10,000 스텝 동안 학습 데이터 로더 구동 및 손실(loss) 계산 시도"
  - then "배치 내 두 데이터 도메인 간 비율이 지정된 $50 \pm 5\%$ 오차 내에서 유지되어야 하며, 데이터 대기로 인한 GPU 대기율(GPU idle time)이 전체 5% 미만이어야 한다"
- **Tests:** `unit/test_mixed_dataset_loader.py`
- **Evidence:** `evidence_pack/REQ-301_data_mixture_log.json`

---

## REQ-302: Simulator Parameter Calibration
- **ID:** REQ-302
- **Context:** 합성-실제 간 도메인 격차를 줄이기 위해 실제 환경(Real observations)으로부터 잔향, 노이즈, 기기 특성 프로파일을 추정하고 이를 시뮬레이터 파라미터로 피드백해야 함.
- **Inputs:** 
  - Unlabeled Real Data (wav files)
  - Pre-defined feature extractors (e.g., RT60 estimator, SNR estimator)
- **Outputs:** Updated Simulator YAML Configuration dictionary.
- **Constraints:** 캘리브레이션 추정 오차가 참값 대비 일정 한도(예: RT60 오차 15% 미만) 수준이어야 함.
- **Acceptance Criteria:**
  - given "RT60 $\approx 0.5s$를 가지는 특정 회의실 측정 데이터 100개"
  - when "Real-data acoustic profile estimation 함수 호출"
  - then "추출된 RT60 통계값의 중앙값이 $0.5s \pm 0.075s$ 안에 있어야 하며, 생성된 시뮬레이터 파라미터로 재생성한 데이터의 RT60 분포가 측정 분포와 KL-divergence 0.1 이하로 일치해야 한다"
- **Tests:** `integration/test_simulator_calibration.py`
- **Evidence:** `evidence_pack/REQ-302_calibration_distributions.png`

---

## REQ-303: Cross-Domain Robustness (Device/Environment Mismatch)
- **ID:** REQ-303
- **Context:** 단일 기기나 룸 구조에 과적합되지 않는 일반화된 분리/음성인식 성능을 확보하기 위한 Robustness Augmentation 기법을 통과해야 함.
- **Inputs:** Base synthetic audio tensor
- **Outputs:** Environment/Device Augmented audio tensor
- **Constraints:** 증강(Augmentation) 파이프라인의 적용 전후 신호 형태(phase, amplitude) 왜곡이 허용 가능한 범위 내이거나 물리적 타당성을 위배하지 않아야 함.
- **Acceptance Criteria:**
  - given "특정 방 A로 학습된 기준(baseline) 분리 모델과 Augmentation이 적용된 향상(Robust) 모델"
  - when "방 B(완전히 보지 못한 새로운 도메인)의 실제 테스트 데이터 세트에 대한 SDR 측정"
  - then "향상 모델의 테스트 셋 SDR이 기준 모델에 비해 최소 1.5dB 이상 일관되게 높아야 하며, 학습 시 본 적이 없는 3종 이상의 마이크 배열 환경 모두에서 성능 하락폭이 기준 모델 대비 절반 이하여야 한다"
- **Tests:** `e2e/test_robustness_heldout_mics.py`
- **Evidence:** `evidence_pack/REQ-303_domain_generalization_report.pdf`

---

## REQ-304: Domain Adaptation / Pretraining Integration
- **ID:** REQ-304
- **Context:** Self-supervised 학습 또는 Domain Adaptation(적대적 학습 등) 기반 아키텍처를 호환시켜 Unlabeled 데이터로부터의 Representation 이득을 취할 수 있어야 함.
- **Inputs:** Model Enc/Dec architecture definition, Adaptation Loss function (e.g., Gradient Reversal Layer, Contrastive Loss)
- **Outputs:** Domain-invariant feature representations (Tensor `[B, C, T]`).
- **Constraints:** 도메인 분류기의 Accuracy가 Random guess 수준(이진 분류 시 $\approx 50\%$)에 수렴할 만큼 특징 추출기가 도메인 불변성을 유지해야 함.
- **Acceptance Criteria:**
  - given "Synthetic 1,000시간과 Real 1,000시간 데이터 셋"
  - when "Domain-invariant feature learning 적대적 학습 50 에폭 가동"
  - then "Discriminator가 예측하는 Synthetic 여부 확률의 이진 교차 엔트로피(BCE) 손실이 0.69 근방에서 횡보하고 유의미하게 0으로 떨어지지 않아야 한다"
- **Tests:** `integration/test_domain_adversarial.py`
- **Evidence:** `evidence_pack/REQ-304_dann_loss_curves.csv`

---

## REQ-305: Gap Reduction Evidence via Downstream Tasks
- **ID:** REQ-305
- **Context:** 위성 기능들이 단순히 합성 성능이 방해받지 않았음을 넘어 실제 다운스트림 태스크(ASR, Diarization)에서 유의미한 성능 이득을 증명해야 함.
- **Inputs:** Processed test utterances, Downstream ASR / Diarization evaluator.
- **Outputs:** Real-world metrics (WER, DER, SDR).
- **Constraints:** Ablation Study를 통해 각 향상 전략(Augmentation, Mixed Data, Calibration)의 기여도를 분리 추정해야 함.
- **Acceptance Criteria:**
  - given "Baseline 모델 출력물과 전략 적용(Gap Reduction) 모델의 출력물"
  - when "Real-world validation loop 상에서 Kaldi 또는 Whisper ASR 파이프라인 통과"
  - then "Gap Reduction이 적용된 모델 파형에 기반한 ASR 단어오류율(WER)이 Baseline 모델 출력물 대비 절대수치 3.0%p 이상 감소해야 하며, Factor attribution 테이블이 모든 요인 별 영향을 합리적으로 도출해야 한다"
- **Tests:** `e2e/test_downstream_eval_pipeline.py`
- **Evidence:** `evidence_pack/REQ-305_downstream_wer_ablation_table.md`
