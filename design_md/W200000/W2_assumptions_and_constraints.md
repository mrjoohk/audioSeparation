# Stage 3: Assumptions and Constraints (W200000 Synthetic Data Generation)

## 1. Constraints (제약 조건)

- **Scale & Footprint:** 
  - 생성 파이프라인은 최대 100,000시간 분량의 오디오셋 생성을 지원해야 함. 데이터 저장은 압축/샤딩(Sharding)을 통해 단일 파일시스템 폴더에 10,000개 이상의 파일이 집중되지 않도록 관리해야 함.
- **Concurrency & Compute Target:**
  - Data Generation 파이프라인은 멀티 워커 클러스터 환경을 지원하며, 전체 10만 시간 생성은 1000 코어 클러스터 기준 1주일 내 완료되어야 함(Generation Speedup > 50x per core).
- **Speaker Counting:** 
  - 음성 겹침(Overlap) 시나리오는 최대 5인(5 concurrent speakers)까지만 혼합하며 그 이상은 다루지 않음.

## 2. Boundary Conditions (경계 조건)

- **Empty/Mute Utterances:** 
  - 0초 길이의 음성 파일이 렌더링되려 하거나 코퍼스 내 완전 무음 파일이 입력될 경우, 해당 잡(Job)은 조기 실패(Fail-fast)하고 매니페스트에 원인 코드를 기록해야 함.
- **Extreme Target SNR:** 
  - 신호 대 잡음비(SNR)가 -20dB 미만(거의 노이즈만 있는 상태)이 되는 극단적 설정 시나리오도 예외 오류를 발생시키지 않고 노이즈가 지배적인 파형으로 정상 생성해야 하나, QC 플래그를 통해 'Extreme' Difficulty로 자동 태깅해야 함.
- **100% Continuous Overlap:** 
  - 두 화자의 음성이 정확히 시작부터 끝까지 100% 겹치는 특이 시나리오(True Overlap)가 요청될 경우 충돌 없이 생성되어야 함.

## 3. Assumptions (가정)

- **Source Asset Cleanliness (원본 코퍼스 무결성):** 
  - Ingestion 단계(W221000)를 통과한 'Clean Speech' 자산은 잔향이나 배경 소음이 없는 무반향(Anechoic)이거나 40dB 이상의 높은 SNR을 가진다고 가정함.
- **Speaker Independence & Leakage (발화자 독립성):** 
  - Train / Val / Test 분할 수행 시 발화자 ID(Speaker Leakage)와 방/기기 구성은 통계적으로 독립적이며 매니페스트 메타데이터 상의 식별자(ID)를 100% 신뢰할 수 있다고 가정함.
- **Label Exactness (레이블 정확성):** 
  - 자동 생성된 타임스탬프, 발화 위치(DOA), VAD 레이블은 시뮬레이터 렌더링 과정에서 샘플 단위(Sample-accurate) 수준으로 절대적으로 일치하며, 지연 오차가 발생하지 않음을 가정함.
