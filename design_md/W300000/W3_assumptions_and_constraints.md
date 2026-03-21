# Stage 3: Assumptions and Constraints (W300000 Synthetic-to-Real Training)

## 1. Constraints (제약 조건)

- **Data Availability Limit:** 
  - 학습 시 사용할 수 있는 Labeled Real Data (실제 측정+정답 레이블 포함) 분량은 전체 학습 데이터의 5% 미만으로 극히 제한된다고 제약함. Unlabeled Real Data는 상대적으로 더 크지만 검증을 통과한 데이터셋만 사용 가능.
- **Compute Overhead:** 
  - Domain Adaptation 방식(예: Adversarial Training)이나 Self-supervised Learning 적용 시, 기본 Supervised 모델 학습 대비 메모리 및 연산 시간의 증가폭이 2배(2x)를 초과해서는 안 됨.
- **Calibration Latency:**
  - Real 데이터 관측치로부터 시뮬레이터 파라미터를 역추정(Calibration Loop)하는 1회 평가 사이클은 클러스터 환경에서 최대 24시간 내에 수렴해야 함.

## 2. Boundary Conditions (경계 조건)

- **Extreme Mismatch:** 
  - Synthetic과 Real 환경의 SNR 스펙트럼 차이가 20dB 이상, RT60 차이가 1.0s를 넘는 극심한 도메인 불일치(Domain gap) 상황에서도 학습 파이프라인이 발산(Divergence)하지 않고 정상적인 Gradient 흐름을 유지해야 함.
- **Zero Real Data Calibration:** 
  - 특정한 새 디바이스에 대해 수집된 Real Data가 단 한 건도 없는 상황(Zero-shot)에서도 시뮬레이터 기반 Curriculum 학습만으로 모델이 동작해야 함(Baseline 보장).
- **Curriculum Stagnation:**
  - Curriculum 단계 승급 기준을 통과하지 못해 학습이 장기간 정체될 경우, Early Stopping 또는 난이도 재조정 로직을 강제 발동하여 데드락 상태를 방지해야 함.

## 3. Assumptions (가정)

- **Stationarity of Real Data (실제 데이터의 분포 정지성):** 
  - 측정된 Real Data의 음향학적 분포(Device, Room 앙상블 등)는 단기적으로 변하지 않는 대표성을 지닌다고 적어도 한 번의 모델 학습 사이클 내에서는 가정함.
- **Factor Independence (요소 독립성):** 
  - 시뮬레이터 보정(Calibration) 시 잔향(Reverb), 노이즈(Noise), 간섭(Interference) 등의 도메인 격차 요인은 상호 파괴적이지 않고 독립적으로 조정 및 최적화가 가능하다고 근사함.
- **Metric Proxy (대리 지표 활용):** 
  - 실제 다운스트림 성능(e.g., WER, DER)을 매 미니배치마다 직접 최적화할 수 없으므로, SDR(Signal-to-Distortion Ratio)나 Contrastive Loss 등의 메트릭이 다운스트림 성능 향상과 양의 상관관계를 가짐을 가정함.
