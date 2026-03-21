# Stage 3: Assumptions and Constraints (W100000 Spatial Simulator)

## 1. Constraints (제약 조건)

- **Performance & Budget:**
  - 시뮬레이터는 대규모 합성 데이터 생성을 위해 실행되어야 하므로 배치 렌더링(Batch rendering) 속도가 실시간 배수(Real-time factor) 0.1 이하를 달성해야 함. (즉, 10초 음원 생성에 1초 이내 소요)
  - 메모리 사용량은 단일 scene 렌더링 시 최대 4GB를 넘지 않아야 하며, 병렬 워커 구동을 지원해야 함.
- **Audio Specifications:**
  - **Sample Rate:** 16 kHz 또는 48 kHz (설정 가능). 하위 태스크(Speech Separation 등)를 위해 기본 16 kHz를 보장해야 함.
  - **Resolution:** 16-bit PCM 및 32-bit Float 지원.
- **Scene Complexity Bounds:**
  - 단일 방(Room) 최대 크기: $50m \times 50m \times 20m$ 이하.
  - 음원(Source) 개수: 최대 동시 10개.
  - 마이크로폰 채널 수: 최대 64채널.
  - 반사 차수(Reflection order): 최대 10차까지 명시적 Image-Source Method 적용 지원.
- **RT60 (Reverberation Time):** 0.1s ~ 5.0s 범위 내에서 시뮬레이션 가능해야 함.

## 2. Boundary Conditions (경계 조건)

- **Zero-source condition:** 음원이 없는 경우, 센서 자체 노이즈(Sensor self-noise)만 출력되어야 함.
- **Extreme Room Dimensions:** 방의 한 변의 길이가 극단적으로 짧은 경우(예: 1m 이하), 잔향 생성 엔진은 수치적 불안정성 없이 빠르게 수렴하거나 평면파 반사 모드로 폴백(fallback)해야 함.
- **Collocated Source and Microphone:** 음원과 마이크가 동일 위치(거리=0)에 배치되는 경우, 무한대 이득(gain) 오류를 피하기 위해 최소 거리 컷오프(예: 0.01m)를 강제해야 함.
- **Moving out of bounds:** 이동하는 음원이나 청취자가 방의 경계를 벗어나려 할 때, 시뮬레이터는 클리핑(충돌 처리)하거나 에러를 반환해야 함.

## 3. Assumptions (가정)

- **Medium Uniformity (매질 균일성):** 공기는 균일한 매질이며, 방 안에서 온도, 습도, 기압의 공간적 변화는 무시함(음속 상수 $\approx 343 m/s$).
- **Rigid Wall Approximation (강체 벽체 근사):** 방의 형태는 평면 벽의 조합으로 이루어지며, 벽면의 진동(Structural vibration) 및 저주파 투과(Transmission) 손실은 1차 근사 모델을 넘어 모델링하지 않음.
- **Far-field Source Approximation (원거리장 가정):** 단일 음원은 이상적인 포인트 소스(Point source)로 간주되며, 음원의 크기나 형태에 따른 근거리장(Near-field) 복잡성은 생략함(필요시 확장 가능).
- **Static Geometry during Propagation:** 단일 프레임 내파(Acoustic propagation)가 일어나는 동안 방의 기하구조는 변하지 않는다고 가정함(동적 모션 변화는 프레임 단위 또는 세그먼트 단위로 갱신).
- **HRTF Stationarity (HRTF 정지성):** 인간의 머리/귀 모양 리시버 시뮬레이션을 위한 HRTF(Head-Related Transfer Function)는 사전 측정된 정적 데이터베이스(SOFA 형식 등)를 보간하여 사용하며, 머리의 미세 변형은 무시함.
