# Stage 4: Requirements (W100000 Spatial Simulator)

## Overview
This document specifies the software requirements for the W100000 Spatial Simulator, following the core-engineering 8-stage design process. The requirements are transformed from the initial high-level objectives in `W100000_Spatial_Simulator_Design.md` (§2).

---

## REQ-001: Scene Geometry & Material Properties
- **ID:** REQ-001
- **Context:** 시뮬레이터는 기본 박스형 공간 및 커스텀 메쉬 기하구조를 렌더링하고 각 표면의 음향학적 성질을 반영해야 함.
- **Inputs:** 
  - Room dimensions `[x, y, z]` (m) or 3D Mesh `(vertices, faces)`
  - Surface material type or absorption coefficients `alpha(f)` for 6-octave bands (0.0 to 1.0)
- **Outputs:** Validated 3D coordinate map & boundary collision regions.
- **Constraints:** 최대 방 크기 50m x 50m x 20m. 메쉬 임포트는 닫힌 공간(Water-tight)이어야 함. 최소 폴리곤 수는 10,000개 미만 제한.
- **Acceptance Criteria:**
  - given "방 크기 [10, 5, 3]m 및 콘크리트 재질"
  - when "초기화 메서드 호출"
  - then "6개의 벽체가 생성되고 체적 $150m^3$이 반환되며 전체 소요시간 < 10ms 여야 한다"
- **Tests:** `unit/test_room_geometry.py`
- **Evidence:** `evidence_pack/REQ-001_geometry_validation.json`

---

## REQ-002: Dynamic Object/Sensor Placement
- **ID:** REQ-002
- **Context:** 음원과 마이크, 혹은 방해물(Obstacles)을 정지 또는 직진/무작위 보행 등 동적인 궤적으로 3D 공간에 배치해야 함.
- **Inputs:** 
  - Source positions `[N, 3]` (m) or trajectory `[T, N, 3]` (m)
  - Receiver (Mic/Listener) positions `[M, 3]` or trajectory `[T, M, 3]`
  - Room bounds.
- **Outputs:** 시간별 업데이트된 글로벌 좌표계 위치 배열.
- **Constraints:** 동시 최대 소스 10개, 마이크 64채널. 모든 좌표는 방 내부(Bounds)에 위치해야 하며 벽/장애물과 충돌(최소거리 0.1m)하면 안 됨.
- **Acceptance Criteria:**
  - given "경계가 [10, 10, 10]인 방에서 소스를 [11, 5, 5]에 배치 시도"
  - when "배치 유효성 검사 수행"
  - then "Out of bounds 에러를 발생시켜야 한다"
- **Tests:** `unit/test_trajectories.py`
- **Evidence:** `evidence_pack/REQ-002_trajectory_plots.png`

---

## REQ-003: Acoustic Propagation Engine (RIR Generation)
- **ID:** REQ-003
- **Context:** 직진 경로, 벽의 반사, 잔향(Reverberation) 엔진, 부분 가림(Occlusion)을 통합하여 RIR(Room Impulse Response)을 생성해야 함.
- **Inputs:** 
  - Validated Room Geometry
  - Source/Mic positions and orientation states
  - Max reflection order (int, e.g. 10)
- **Outputs:** `RIR tensor [N_sources, N_mics, time_samples]` (Float32).
- **Constraints:** Target RT60 오차율 < 10% 내외 유지. Image-Source Method + Stochastic Ray Tracing 융합.
- **Acceptance Criteria:**  
  - given "동일 위치에 배치된 단일 소스와 1채널 마이크 (d=1m) 및 반사 차수 1"
  - when "RIR 렌더링"
  - then "직접파 딜레이는 $\approx 2.9ms$에 피크를 가져야 하고, 지정된 RT60 목표치 0.3s와 측정된 T60 간 오차가 0.03s 미만이어야 한다"
- **Tests:** `integration/test_rir_acoustics.py`
- **Evidence:** `evidence_pack/REQ-003_rt60_measurements.csv`

---

## REQ-004: Multi-channel & Binaural Support
- **ID:** REQ-004
- **Context:** 모노 마이크뿐 아니라 방향성이 있는 어레이 기하 및 양이(Binaural) 머리 회전까지 포함하는 마이크로폰 구성을 지원해야 함.
- **Inputs:** 
  - Array topology schema (e.g. ULA, UCA, Sphere configuration) 
  - HRTF Dataset `(elevation, azimuth) -> BRIR`
- **Outputs:** 채널 수가 일치하는 공간 반사 응답.
- **Constraints:** HRTF 보간 오차 최소화. 어레이 마이크 간 거리는 최저밀리미터 수준(예: 0.04m)까지 정확히 보존.
- **Acceptance Criteria:**
  - given "반경 5cm의 원형 어레이(UCA, M=4)"
  - when "임의의 음원 신호 렌더링 및 DOAs 검사"
  - then "출력 신호 간 위상차(Phase difference)가 수학적 기하 지연과 0.1 샘플(16kHz 기준) 이내로 일치해야 한다"
- **Tests:** `unit/test_array_topology.py`
- **Evidence:** `evidence_pack/REQ-004_array_coherence.pdf`

---

## REQ-005: Capture Chain Reelism & Imperfections
- **ID:** REQ-005
- **Context:** 이상적 센서를 사실적 센서 데이터로 바꾸기 위해 하드웨어적 결함(Noise, clipping, clock skew, codec artifact)을 모사해야 함.
- **Inputs:** Clean simulated multi-channel audio tensor (Float32)
- **Outputs:** Impaired audio tensor (Float32 or Int16)
- **Constraints:** SNR은 0dB에서 무한대(Clean) 사이. 마이크별 감도 오차(Sensitivity variation) $\pm 2$dB 허용.
- **Acceptance Criteria:**
  - given "클래핑(clipping) 임계값을 넘는 증폭 게인을 가진 입력 신호"
  - when "Electronic noise and gain modeling 단계"
  - then "임계값 이상 부분에 하드 클리핑이 적용되고 THD(Total Harmonic Distortion)가 일정비율 증가해야 한다"
- **Tests:** `unit/test_impairments.py`
- **Evidence:** `evidence_pack/REQ-005_sensor_noise_spectra.png`

---

## REQ-006: Simulator Orchestration and Export
- **ID:** REQ-006
- **Context:** 시뮬레이터 구동, 씬(Scene) 정보의 메타데이터화, 최종 오디오 파형과의 동기화 저장을 지원해야 함.
- **Inputs:** Generated Audio `[C, T_samples]` and all context metadata dictionaries.
- **Outputs:** Data bundle (`.wav` + `.json` manifest).
- **Constraints:** 디스크 I/O 속도 최적화. 폴더 당 최대 10,000개 파일 관리 가능.
- **Acceptance Criteria:**
  - given "30초 길이, 8 마이크, 4 소스의 시뮬레이션 결과"
  - when "export 함수 호출"
  - then ".wav 파일과 .json 포맷의 매니페스트가 생성되며, json에서 4개 소스의 배치 및 이벤트 타임라인이 누락없이 기록되어야 한다"
- **Tests:** `integration/test_export_pipeline.py`
- **Evidence:** `evidence_pack/REQ-006_metadata_schema_valid.json`

---

## REQ-007: Deterministic Reproducibility
- **ID:** REQ-007
- **Context:** 기계학습 학습 데이터 생성시 동일 시드를 주면 완전히 동일한 씬과 오디오를 출력해야 함.
- **Inputs:** Pseudo-random global `seed` (int).
- **Outputs:** Deterministic identical outputs for the same seed.
- **Constraints:** 동일 시드에 대해 32비트 Float 연산 라운딩 오차를 제외하고 모든 메타데이터와 난수 발생기 상태가 100% 동일해야 됨. 플랫폼 무관한 난수 샘플러 사용 우선.
- **Acceptance Criteria:**
  - given "시드 번호 42로 설정된 동일 잡(Job) 파라미터 2세트"
  - when "렌더링 구동"
  - then "생성된 두 출력 텐서의 MAE(Mean Absolute Error)가 0 이어야 한다"
- **Tests:** `integration/test_reproducibility.py`
- **Evidence:** `evidence_pack/REQ-007_seed_diff_log.txt`

---

## REQ-008: Batch Scalability & Generation Budget
- **ID:** REQ-008
- **Context:** 향후 100,000시간 분량의 합성 데이터 세트 구축을 지탱하기 위한 계산 파이프라인의 효율성/병렬성을 확보해야 함.
- **Inputs:** `N` distinct simulation jobs (e.g. `N=1000`).
- **Outputs:** Processed batches across local or cluster nodes.
- **Constraints:** 초과 메모리 릭(Memory leak) 방지. Python의 GIL을 우회하기 위한 Multi-processing 또는 HPC Queue 연동 가능.
- **Acceptance Criteria:**
  - given "서로 다른 시드의 잡 100개, 단일 노드(8코어)"
  - when "`run_batch` 호출"
  - then "100개 잡 처리가 멀티프로세싱을 통해 순차 처리대비 5배 이상 빨라야 하며(Speedup > 5x), OOM 에러 없이 완료되어야 한다"
- **Tests:** `e2e/test_batch_scaling.py`
- **Evidence:** `evidence_pack/REQ-008_runtime_profile.csv`
