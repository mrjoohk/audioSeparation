# Stage 3: Assumptions and Constraints (W400000 Validation & Downstream)

## 1. Constraints (제약 조건)

- **Compute/Time Bounds:** 
  - 검증 평가(Validation & Benchmark Run)는 CI/CD 환경에서 모델 학습 완료 후 12시간 내에 전체 벤치마크 스위트(SI-SDR, WER, DER 통합) 평가를 끝내야 함.
- **Metric Compute Hardware:**
  - 평가 스크립트는 멀티 GPU가 없는 단일 워커 노드(CPU Only 또는 1 GPU) 환경에서도 실행 가능해야 하며, 평가 중 모델 추론 메모리 점유율이 8GB를 넘지 않아야 함.
- **Data Privacy & Compliance:**
  - Real-world Benchmark 파임스크립트 사용 시 내부 보안 규정을 준수하여 민감 정보 스크러빙(Scrubbing)이 보장된 데이터만 에러 분석용으로 보관 및 활용 가능함.

## 2. Boundary Conditions (경계 조건)

- **Zero Gain Mismatch:** 
  - 특정 엣지 케이스(예: 잔향 0초의 아네코익(Anechoic) 환경)에서 음원 분리가 오히려 신호 왜곡을 발생시킬 수 있는 조건일지라도 알고리즘 페일(Crash)이 일어나지 않고 신원을 통과시켜야 함.
- **OOM on Edge Cases:** 
  - 극단적인 스피커 오버랩(e.g., 동시 화자 10명)이 포함된 Stress Benchmark를 입력받았을 때, 모델은 메모리 한계 내에서 분리 불가(Fail/Fallback) 결정을 내리더라도 예외 발생(Exception) 없이 완료해야 함.
- **Null Reference:** 
  - 비지도(Unsupervised) 리얼 테스트셋의 경우 Clean Reference 파형이 존재하지 않아 분리 Metric(SI-SDR 등) 연산이 불가능하므로, ASR/DER 다운스트림 메트릭이나 비참조(Reference-free) 메트릭 체계로 자동 폴백해야 함.

## 3. Assumptions (가정)

- **Downstream Proxy Validity:** 
  - SI-SDR/PESQ 와 같은 Signal-level Metric 향상이 ASR(WER)과 Diarization(DER) 성능의 향상으로 비례적 연결성을 띄는 합당한 워터마크임(Proxy)을 가정함.
- **Benchmark Stationarity:** 
  - 확정된 Synthetic Benchmark와 Real-world Benchmark Suite의 분포와 라벨은 검증 과정 중에 불변성을 띄며(동결), 성능 비교의 절대적 기준점 그라운드 트루스로 작용할 수 있음을 가정함.
- **Frontend-Backend Independence:** 
  - 음원 분리(Frontend module)의 영향력을 측정할 때 다운스트림에 사용되는 ASR/Diarization 모델(Backend module)은 고정되어 있으며(Frozen), Backend 모델 자체의 결함으로 인한 성능 왜곡은 전체 시스템 상수(Constant factor)로 취급함.
