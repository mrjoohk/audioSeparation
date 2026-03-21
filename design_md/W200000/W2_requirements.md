# Stage 4: Requirements (W200000 Synthetic Data Generation)

## Overview
This document specifies the software requirements for the W200000 Synthetic Data Generation capability, derived from the core-engineering 8-stage design process. The requirements operationalize the goals listed in `W200000_Synthetic_Data_Generation_Design.md` (§2) into testable BDD formats.

---

## REQ-201: Parametric Scenario Generation at Scale
- **ID:** REQ-201
- **Context:** 특정 교실, 회의실, 차량 내부 등 다양한 방 구조, 마이크, 소음, 기기 파라미터를 갖는 수만 가지의 학습용 시나리오를 자동 생성해야 함.
- **Inputs:** 
  - `scenario_config.yaml` specifying prior distributions for $P(\text{room})$, $P(\text{mic})$, $P(\text{sources})$
  - Target sample count $N$
- **Outputs:** $N$ distinct Scenario Manifest JSON files
- **Constraints:** 생성 속도는 단일 서버에서 1초당 1000개 시나리오 이상 도출해야 함.
- **Acceptance Criteria:**
  - given "Room length= [3m, 10m], Source count=[1, 4] 파라미터 제약조건"
  - when "10,000건의 시나리오 샘플링 스크립트 실행"
  - then "10초 이내에 완료되며, 생성된 시나리오 중 Length 범위를 벗어나거나 Source count 제약을 어긴 결과가 0건이어야 하고, 겹치는 해시(Duplicate scenarios)가 $0.1\%$ 미만이어야 한다"
- **Tests:** `unit/test_scenario_sampling.py`
- **Evidence:** `evidence_pack/REQ-201_manifest_duplicates.csv`

---

## REQ-202: Audio Asset & Noise Composition
- **ID:** REQ-202
- **Context:** 전처리된 클린 스피치, 배경 노이즈, 방해음(Interference), 순간 이벤트 음원 등을 조합하여 실제와 같은 Mixture 오디오를 렌더링해야 함.
- **Inputs:** 
  - Clean speech stem (16kHz, Float)
  - Selected Noise stem 
  - SNR Target (e.g., 5dB)
- **Outputs:** Mixture audio tensor `[C, T_samples]` and individual reference stems `[Sources, C, T_samples]`.
- **Constraints:** 렌더링된 결과물의 SNR이 정해진 목표 SNR $\pm 1dB$ 범위 내여야 함.
- **Acceptance Criteria:**
  - given "1명의 발화자, 1개의 에어컨 노이즈 음원, 목표 SNR = 5dB"
  - when "Mixture 렌더링 파이프라인(Asset assembly) 작동"
  - then "출력 텐서의 RMS 에너지를 기반으로 에어컨 노이즈 성분을 빼고 계산된 활성 발화 구간(active speech level)의 SNR이 $5dB \pm 1dB$ 내로 수렴해야 한다"
- **Tests:** `integration/test_snr_composition.py`
- **Evidence:** `evidence_pack/REQ-202_snr_validation_plot.png`

---

## REQ-203: Dynamic Scenes and Difficulty Tiers
- **ID:** REQ-203
- **Context:** 시뮬레이터와 결합하여 화자의 이동(Motion), 중간 발화 시작/종료 등의 동적인 이벤트를 스케줄링하고 데이터셋을 난이도 별로 분리 생성해야 함.
- **Inputs:** 
  - Trajectory generators $v(t)$, $xyz(t)$
  - Overlap ratio target list (e.g., 0%, 20%, 50%)
- **Outputs:** Scheduled Event Timelines & dynamic mixture audio.
- **Constraints:** 설정된 다자간 Overlap 커버리지 목표(Target ratio)와의 오차범위 5% 미만 유지.
- **Acceptance Criteria:**
  - given "클래스 `Hard` 난이도(Overlap ratio 50% 타겟)의 시나리오 1,000건 생성 요청"
  - when "Event Scheduler 및 렌더링 수행"
  - then "생성된 1,000건의 VAD 레이블을 모두 취합하여 계산한 최종 실제 화자간 겹침 비율 누적이 $50\% \pm 5\%$ 이어야 한다"
- **Tests:** `unit/test_overlap_scheduler.py`
- **Evidence:** `evidence_pack/REQ-203_tier_distribution.json`

---

## REQ-204: Label Generation and Synchronization
- **ID:** REQ-204
- **Context:** 하위 태스크(Separation, VAD, Diarization, ASR) 모형 학습을 위해 혼합 오디오와 정밀하게 밀착 동기화된 메타데이터 및 레이블을 생성해야 함.
- **Inputs:** Generated Audio `[C, T]`, Simulation state arrays `(Time, Pos, Source_ID, Activity)`.
- **Outputs:** 
  - Speaker Session Labels
  - VAD / Overlap binary targets
  - Target DOA traces
- **Constraints:** 프레임 타임스탬프 동기화 정밀도는 $1ms$ 미만 (16kHz 기준 16샘플 미만 오차).
- **Acceptance Criteria:**
  - given "2명 화자의 간헐적 발화(Turn-taking)가 있는 10초짜리 Mixture"
  - when "Label generation 추출"
  - then "추출된 VAD Ground Truth 배열 1 값이 Clean Stem 오디오의 $>-40dB$ RMS 에너지 영역과 $\pm 1ms$ 타임스탬프 마진 내에서 정확히 일치(F1 Score > 0.999)해야 한다"
- **Tests:** `integration/test_label_sync.py`
- **Evidence:** `evidence_pack/REQ-204_vad_alignment.pdf`

---

## REQ-205: Quality Control and Dataset Lifecycle
- **ID:** REQ-205
- **Context:** 손상되거나 비정상적인 데이터(clipping, silence)를 파이프라인 단에서 자동으로 필터링하고 데이터셋 버전을 지정, 패키징하여 재현성을 보장해야 함.
- **Inputs:** Unfiltered generated batches (Wav files & JSONs).
- **Outputs:** QC-passed, version-tagged, tar/sharded Dataset folder.
- **Constraints:** 클리핑된 샘플(Max amp >= 0.99) 누락 0%, 완전 무음 샘플 0% 보장.
- **Acceptance Criteria:**
  - given "의도적으로 5%의 파일을 클리핑 되게 게인(Gain)을 증폭 설정한 배치 생성물"
  - when "Automated QC Check 및 Dataset Packaging 구동"
  - then "클리핑 규칙 위반으로 정확하게 5%의 파일이 거부(Rejected)되어야 하며, 통과된 최종 릴리스 패키지엔 클리핑 파일이 0건으로 확인되어야 한다."
- **Tests:** `unit/test_qc_gates.py`
- **Evidence:** `evidence_pack/REQ-205_qc_rejection_logs.txt`

---

## REQ-206: Leakage-Free Data Splitting
- **ID:** REQ-206
- **Context:** 학습 과정에서 모델이 훈련 셋의 특정 화자, 방 구조, 노이즈 패턴을 단순 암기하지 못하도록 독립적인 Train/Val/Test 분할을 수행해야 함.
- **Inputs:** Asset Library metadata IDs, Split ratios (e.g. 80/10/10).
- **Outputs:** `train.txt`, `val.txt`, `test.txt` manifest lists.
- **Constraints:** 스피커, 룸(Room 임포트 메시), 그리고 배경 노이즈 원본 ID에 대해 훈련/초평가/평가 간의 교집합(Leakage)이 완전히 없어야 함 (Strict zero leakage).
- **Acceptance Criteria:**
  - given "전체 스피커 100명, 노이즈 50종의 Asset 셋과 80/10/10 파티션 명령"
  - when "분할(Partitioning) 동작"
  - then "Test split 매니페스트에 나타난 `speaker_id` 집합과 Train/Val 매니페스트의 `speaker_id` 집합 간 교집합 원소 개수가 0개여야 하며, 동일 검사가 `noise_id` 에 대해서도 통과되어야 한다"
- **Tests:** `unit/test_dataset_leakage.py`
- **Evidence:** `evidence_pack/REQ-206_leakage_audit.json`
