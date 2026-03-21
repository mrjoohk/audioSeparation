# W100000 Spatial Audio Simulator — 프로젝트 요약

> 작성일: 2026-03-21 | 버전: 1.0.0

---

## 1. 프로젝트 개요

**목적:** 음성 분리(Speech Separation) AI 모델 학습을 위한 3D 공간 음향 데이터셋을 자동 생성하는 시뮬레이터

**핵심 기능:**
- 가상 방(Shoebox/Mesh) 내부의 음원·수음기 배치
- Image Source Method(ISM) 기반 Room Impulse Response(RIR) 생성
- 동적 음원/수음기 궤적 시뮬레이션
- 마이크 배열 특성 + 잡음 + 코덱 열화 모델링
- 대규모 배치 데이터셋 자동 생성 + 메타데이터 내보내기

---

## 2. 설계 아키텍처

### 계층 구조

```
Simulator (Facade)
└── SimulatorOrchestrator (IF-W155)
    ├── SceneWorldBuilder      (IF-W11x)  ← 방·재질·장애물·좌표계
    ├── AcousticPropagationEngine (IF-W12x) ← 직접파·반사·폐색·RIR
    ├── DynamicSceneOrchestrator  (IF-W13x) ← 궤적·동기화·동적 렌더링
    ├── CaptureDeviceChain     (IF-W14x)  ← 마이크·배열·잡음·코덱
    └── BatchExecutor          (IF-W15x)  ← 설정·배치·메타데이터·시각화
```

### 전체 데이터 흐름

```
SceneConfig (YAML/JSON)
    → SceneConfigValidator
    → SceneWorldBuilder.build_all()        # SceneState 타임라인 생성
    → AcousticPropagationEngine.generate_all_rirs()  # RIR 계산
    → CaptureDeviceChain.process_full_chain()  # 마이크 신호 처리
    → SimulatorOrchestrator.export_results()   # WAV + JSON 내보내기
```

---

## 3. 구현 현황

### 3-1. UF (Unit Function) 구현 현황

| 모듈 범위 | 파일 | UF 수 | 상태 |
|-----------|------|-------|------|
| W111 Room Geometry | `w111_room_geometry.py` | 4 | ✅ 완료 |
| W112 Material DB | `w112_material.py` | 4 | ✅ 완료 |
| W113 Obstacle | `w113_obstacle.py` | 4 | ✅ 완료 |
| W114 Transforms | `w114_transforms.py` | 4 | ✅ 완료 |
| W115 Scene State | `w115_scene_state.py` | 2 | ✅ 완료 |
| W121 Direct Path | `w121_direct_path.py` | 5 | ✅ 완료 |
| W122 Reverberation | `w122_reverberation.py` | 5 | ✅ 완료 |
| W123 Occlusion | `w123_occlusion.py` | 5 | ✅ 완료 |
| W124 RIR Rendering | `w124_rir_rendering.py` | 4 | ⚠️ BRIR STUB |
| W131 Source Trajectory | `w131_trajectory.py` | 4 | ✅ 완료 |
| W132 Receiver Trajectory | `w132_receiver_trajectory.py` | 4 | ✅ 완료 |
| W133 Sync | `w133_sync.py` | 4 | ✅ 완료 |
| W134 Dynamic Render | `w134_dynamic_render.py` | 4 | ⚠️ 동적 RIR STUB |
| W141 Mic Response | `w141_mic_response.py` | 4 | ✅ 완료 |
| W142 Array Geometry | `w142_array_geometry.py` | 4 | ✅ 완료 |
| W143 Noise/Gain | `w143_noise_gain.py` | 4 | ✅ 완료 |
| W144 Codec | `w144_codec.py` | 4 | ✅ 완료 |
| W151 Config | `w151_config.py` | 4 | ✅ 완료 |
| W152 Batch | `w152_batch.py` | 4 | ✅ 완료 |
| W153 Metadata | `w153_metadata.py` | 4 | ✅ 완료 |
| W154 Visualization | `w154_visualization.py` | 4 | ✅ 완료 |
| W155 Validation | `w155_validation.py` | 2 | ✅ 완료 |
| **합계** | **22 files** | **~46 UFs** | **44/46 완료** |

### 3-2. IF (Integration Function) 구현 현황

| 모듈 | 파일 | 상태 |
|------|------|------|
| SceneWorldBuilder | `if_modules/scene_world.py` | ✅ 완료 |
| AcousticPropagationEngine | `if_modules/propagation.py` | ✅ 완료 |
| DynamicSceneOrchestrator | `if_modules/dynamics.py` | ✅ 완료 |
| CaptureDeviceChain | `if_modules/capture.py` | ✅ 완료 |
| SimulatorOrchestrator + `simulate_scene()` | `if_modules/orchestration.py` | ✅ 완료 |
| Simulator Facade | `simulator.py` | ✅ 완료 |

### 3-3. 테스트 현황

| 구분 | 파일 수 | 테스트 케이스 수 | 상태 |
|------|--------|----------------|------|
| 단위 테스트 | 18개 | ~200개 | ✅ 작성 완료 |
| 통합 테스트 | 5개 | ~40개 | ✅ 작성 완료 |
| W122 테스트 | 1개 | 30개 | ✅ 전부 통과 확인 |

### 3-4. GUI

| 구성요소 | 상태 |
|----------|------|
| Gradio 웹 UI (`app.py`) | ✅ 구현 완료 |
| 3D 인터랙티브 룸 프리뷰 (Plotly) | ✅ 구현 완료 |
| Single Scene 생성 탭 | ✅ 구현 완료 |
| Batch 생성 탭 | ✅ 구현 완료 |
| 결과 뷰어 탭 | ✅ 구현 완료 |
| Config I/O 탭 | ✅ 구현 완료 |

---

## 4. 알고리즘 요약

| 알고리즘 | 적용 위치 | 구현 방식 |
|----------|-----------|-----------|
| Allen-Berkley ISM | W122 | Manhattan distance 필터 적용, order×6 소스 생성 |
| Sabine RT60 | W122, W155 | RT60 = 0.161 × V / Σ(αᵢ×Sᵢ) |
| Schroeder 역적분 | W122 | T₆₀ 측정 from RIR |
| ISO 9613-1 공기흡수 | W121 | 옥타브밴드별 감쇠 계수 |
| Maekawa 회절 | W123 | 칼날 회절 근사, N = 2d/λ |
| OLA(Overlap-Add) | W124 | 동적 씬 컨볼루션 |
| SHA-256 시드 유도 | W151 | 서브시스템별 재현 가능 시드 |
| Rejection Sampling | W113 | 장애물 AABB 충돌 방지 배치 |

---

## 5. 발견된 문제점

### 5-1. 수정 완료된 버그

| ID | 문제 | 수정 내용 |
|----|------|-----------|
| **BUG-01** | `w113_obstacle.py`, `w115_scene_state.py`의 `sys.path` 깊이 오류 (3단계→루트) | 2단계로 수정 |
| **BUG-02** | Python `cp949` 인코딩으로 파일 읽기 실패 | `encoding='utf-8'` 명시 |
| **BUG-03** | ISM order=1일 때 26개 소스 반환 (정답: 6개) | Manhattan distance 필터 추가: `abs(nx)+abs(ny)+abs(nz) > ism_order` |
| **BUG-04** | Gradio 6.0에서 `theme` 파라미터 위치 변경 | `Blocks()` → `launch()`로 이동 |

### 5-2. 잔존 STUB (다음 버전 과제)

| ID | 위치 | 문제 | 영향 |
|----|------|------|------|
| **STUB-01** | `w124_rir_rendering.py::generate_brir` | 실제 CIPIC HRTF DB 미사용, 합성 HRTF 사용 | 바이노럴 렌더링 정확도 저하 |
| **STUB-02** | `w134_dynamic_render.py::render_dynamic_scene` | 동적 씬 RIR을 1/r 임펄스 근사 사용 | 움직이는 음원의 음향 정밀도 저하 |

### 5-3. 설계 단계에서 발견된 원본 문제점 (P-01~P-08)

| ID | 문제 | 해결 |
|----|------|------|
| P-01 | 수용 기준 없음 (정량적 임계값 부재) | REQ-W01~W15에 Given/When/Then 형식으로 수치 기준 추가 |
| P-02 | I/O 계약 없음 | 44개 UF 블록 전부 타입·단위·범위 명세 |
| P-03 | 물리적 제약 미정의 | AC-01~AC-10 물리 제약, CC-01~CC-07 계산 제약 문서화 |
| P-04 | UF→IF 커버리지 검증 없음 | 커버리지 매트릭스 작성 (71% COVERED) |
| P-05 | 샘플레이트·틱 크기 미정의 | 16kHz / 20ms 틱 확정 |
| P-06 | HRTF 소스 미정의 | CIPIC DB 사용 결정 (V1은 합성 placeholder) |
| P-07 | ISM 경계조건 미정의 | MAX_RIR_DURATION_S 기반 거리 필터 적용 |
| P-08 | 성능 목표 없음 | REQ-W04(≥1000 RIR/s), REQ-W10(≥1000 씬/h) 추가 |

---

## 6. 개선 방향

### 단기 (v1.1)

| 항목 | 내용 | 난이도 |
|------|------|--------|
| CIPIC HRTF 통합 | `generate_brir()` 에 실제 CIPIC 로더 연결 | 중 |
| 동적 RIR 완전 구현 | `render_dynamic_scene()` 에 `AcousticPropagationEngine.generate_rir()` 연결 | 중 |
| 전체 pytest 자동 실행 | GitHub Actions CI 연동 (`pytest --cov`) | 하 |
| 성능 벤치마크 | REQ-W04·W10 실측 (≥1000 RIR/s, ≥1000 씬/h) | 하 |

### 중기 (v1.2)

| 항목 | 내용 |
|------|------|
| Mesh 방 지원 | `import_mesh_geometry()` + trimesh 완전 연동 |
| GPU ISM | cuPy 기반 이미지 소스 병렬 계산 |
| 실제 RIR 데이터 검증 | ACE Challenge DB와 RT60·DRR 비교 |
| 다중 음원 믹싱 | 복수 음원 신호 컨볼루션 후 믹싱 파이프라인 |
| 소음 프로파일 라이브러리 | DEMAND·NOISEX-92 노이즈 파일 주입 |

### 장기 (v2.0)

| 항목 | 내용 |
|------|------|
| 신경망 RIR 보간 | 데이터 기반 RIR 보간 (e.g., NAF) |
| 이동 음원 도플러 | 속도 기반 피치 시프트 모델링 |
| 실외 전파 모델 | ISO 9613-2 (장거리 옥외 감쇠) |
| REST API 서버 | FastAPI 기반 원격 씬 생성 엔드포인트 |

---

## 7. 파일/디렉토리 구조 요약

```
AudioSeparation/
├── app.py                          ← Gradio GUI 진입점
├── pyproject.toml                  ← 패키지 정의, 의존성
├── conftest.py                     ← pytest sys.path 설정
├── PROJECT_SUMMARY.md              ← 이 문서
├── USER_MANUAL.md                  ← 사용 매뉴얼
├── src/
│   └── simulator/
│       ├── simulator.py            ← Facade 클래스
│       ├── types.py                ← 공유 데이터클래스 35종
│       ├── if_modules/             ← 5개 통합 모듈
│       └── uf/                     ← 22개 단위 함수 파일
├── tests/
│   ├── unit/                       ← 단위 테스트 18개
│   └── integration/                ← 통합 테스트 5개
├── W100000/                        ← 설계 문서 (요구사항, UF/IF 명세)
└── reports/impl/                   ← 구현 현황 리포트
```

---

## 8. 검증된 스모크 테스트 결과 (2026-03-21)

| 항목 | 기댓값 | 실측값 | 결과 |
|------|--------|--------|------|
| Room volume (5×4×3 m) | 60.0 m³ | 60.0 m³ | ✅ |
| 1 m 직접파 지연 @16kHz | 47 samples | 47 samples | ✅ |
| ISM order=1 소스 수 | 6 | 6 | ✅ (BUG-03 수정 후) |
| Sabine RT60 (콘크리트) | ~0.2 s | 0.206 s | ✅ |
| 가시성 테스트 (장애물 없음) | True | True | ✅ |
