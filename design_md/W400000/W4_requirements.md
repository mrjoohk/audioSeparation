# Stage 4: Requirements (W400000 Validation & Downstream)

## Overview
This document specifies the software requirements for the W400000 Proof of Improvement in Downstream Evaluation pipeline, adhering to the core-engineering 8-stage design process. It transforms existing design objectives into testable, metric-driven REQ blocks.

---

## REQ-401: Separation Metric Evaluation (Signal Quality)
- **ID:** REQ-401
- **Context:** 기본 분리 품질을 측정하기 위해 다양한 난이도와 설정(노이즈, 잔향, 객체 이동 등)에 대한 표준 분리 평가 지표(Metric)를 도출해야 함.
- **Inputs:** 
  - Separated hypothesis audio tensors `[Sources, T]`
  - Reference clean audio tensors `[Sources, T]`
- **Outputs:** Evaluation Report mapping (SI-SDR, PESQ, STOI 등).
- **Constraints:** 평가 엔진 처리 속도가 Real-time factor 0.5 미만(오디오 1초당 0.5초 이내 계산)이어야 함. Permutation Invariant Training(PIT) 정렬 필수 지원.
- **Acceptance Criteria:**
  - given "1시간 분량의 Synthetic Benchmark 테스트셋 (2-speaker overlap)"
  - when "Separation metric evaluation 파이프라인 가동"
  - then "1시간 내 연산이 완료되며, 출력된 SI-SDRi(개선율) 결과값이 최소 8.0dB 이상으로 측정되어 Baseline을 초과하고 Metric 요약 JSON이 생성되어야 한다"
- **Tests:** `unit/test_separation_metrics.py`
- **Evidence:** `evidence_pack/REQ-401_sisdr_benchmark.json`

---

## REQ-402: Downstream ASR / Diarization Integrity
- **ID:** REQ-402
- **Context:** 신호 분리 이후의 향상된 오디오가 실제 음성 인식(ASR) 단어 오류율(WER)과 화자 분할(DER) 에러율을 얼마나 감소시키는지 연결 증명해야 함.
- **Inputs:** 
  - Model processed multi-channel or single-channel audio
  - Target text transcriptions & time-aligned speaker labels
- **Outputs:** WER / DER percentage metrics.
- **Constraints:** Backend ASR/Diarization 모델은 Freeze 상태 유지.
- **Acceptance Criteria:**
  - given "Real-world benchmark suite (SNR 5dB, 30% 혼합발화 환경)"
  - when "음원 분리 전처리 통과 후 ASR 및 Diarization 파이프라인 수행"
  - then "음원 분리 미적용시의 기본 파형 대비 분리 후 처리된 음성의 WER 상대 감소율(Relative WER reduction)이 15% 이상이어야 하며, DER은 절대 수치 5.0%p 이상 감소해야 한다"
- **Tests:** `integration/test_asr_der_pipeline.py`
- **Evidence:** `evidence_pack/REQ-402_downstream_gains_table.csv`

---

## REQ-403: Benchmark Suite Integrity & Reproducibility
- **ID:** REQ-403
- **Context:** 테스트의 신뢰도를 보장하기 위해, Synthetic, Real-world, Stress benchmark 셋트가 변조 불가능하고 정확하게 버전 타겟팅되어야 함.
- **Inputs:** Dataset version IDs, Metadata registries.
- **Outputs:** Locked DataLoader validation splits.
- **Constraints:** 벤치마크 스플릿 내 100% Deterministic Ordering 보장 및 Leakage 0% 유지.
- **Acceptance Criteria:**
  - given "버전 태그 `v1.2`로 고정된 Benchmark Metadata YAML"
  - when "서로 다른 3개의 서버에서 데이터 로더를 통해 스위트 호출"
  - then "로드된 데이터 텐서의 sha256 해시가 세 서버 모두 정확히 일치해야 하며 누락된 파편(Shard)이 없어야 한다"
- **Tests:** `integration/test_benchmark_reproducibility.py`
- **Evidence:** `evidence_pack/REQ-403_hash_matching_log.txt`

---

## REQ-404: Causal Ablation and Sensitivity Dashboard
- **ID:** REQ-404
- **Context:** 전체 시스템 성능 향상이 설계 요소 중 어떤 부분(e.g., 시뮬레이터 룸 파라미터 개선, 적대적 도메인 학습 등)의 기여로 이뤄졌는지 상관관계 및 속성(Ablation)을 분석해야 함.
- **Inputs:** Multiple metric JSONs from ablations runs (Base, -Reverb, -Motion, -Adaptation).
- **Outputs:** Causal factor attribution matrix or dashboard graph.
- **Constraints:** 지표 간 교차 상관계수 분석 및 리포트 생성이 자동화되어야 함.
- **Acceptance Criteria:**
  - given "4가지 각기 다른 요인을 하나씩 배제(Ablate)한 4종의 실험 결과 집합"
  - when "Cross-task improvement analysis 및 Dashboard 생성기 구동"
  - then "각 Ablation 요소가 SI-SDR과 WER에 미친 영향(Impact Coefficient)이 퍼센트 기반 표로 자동 컴파일 및 요약 보고서에 누락 없이 PDF 형식으로 출력되어야 한다"
- **Tests:** `unit/test_ablation_parser.py`
- **Evidence:** `evidence_pack/REQ-404_causal_dashboard_v1.pdf`

---

## REQ-405: Automated Regression & Deployment Gating
- **ID:** REQ-405
- **Context:** 새로운 코드/모델 PR(Pull Request)이 승인되기 전, 자동으로 회귀(Regression) 테스트를 거치고 사전에 정의된 Release Gate를 통과해야만 함.
- **Inputs:** Candidate Model checkpoints & Benchmark Suite.
- **Outputs:** CI/CD Pass/Fail boolean decision.
- **Constraints:** CI 파이프라인 타임아웃은 최대 4시간. 임의 조건 하락폭 Tolerance는 1% 미만 허용.
- **Acceptance Criteria:**
  - given "기존 SOTA 모델 대비 실생활 벤치마크(Real-world Suite) 평가에서 WER 예측 지표가 0.5% 나빠진 신규 모델의 평가 트리거"
  - when "Deployment gate criteria 검증 시스템 동작"
  - then "정의된 Degradation 허용 한도(Tolerance) 범위를 초과한 회귀로 감지하여 CI 상태를 'Fail' 로 차단하고, Failure regression 리포트를 출력해야 한다"
- **Tests:** `e2e/test_release_gate_enforcement.py`
- **Evidence:** `evidence_pack/REQ-405_github_ci_gate_log.txt`
