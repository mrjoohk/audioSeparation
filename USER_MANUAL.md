# W100000 Spatial Audio Generator — 사용 매뉴얼

> 버전: 1.0.0 | 최종 수정: 2026-03-21

---

## 목차

1. [설치](#1-설치)
2. [빠른 시작](#2-빠른-시작)
3. [GUI 사용법](#3-gui-사용법)
   - [Tab 1 — Scene Editor](#tab-1--scene-editor)
   - [Tab 2 — Batch Generator](#tab-2--batch-generator)
   - [Tab 3 — Results Viewer](#tab-3--results-viewer)
   - [Tab 4 — Config I/O](#tab-4--config-io)
4. [Python API 사용법](#4-python-api-사용법)
5. [설정 파일(Config) 형식](#5-설정-파일config-형식)
6. [출력 파일 구조](#6-출력-파일-구조)
7. [주요 파라미터 레퍼런스](#7-주요-파라미터-레퍼런스)
8. [테스트 실행](#8-테스트-실행)
9. [자주 묻는 질문 (FAQ)](#9-자주-묻는-질문-faq)
10. [알려진 제한사항](#10-알려진-제한사항)

---

## 1. 설치

### 시스템 요구사항

| 항목 | 최소 사양 | 권장 사양 |
|------|-----------|-----------|
| Python | 3.9+ | 3.13 |
| RAM | 4 GB | 16 GB |
| 저장공간 | 2 GB | 20 GB+ (데이터셋 크기에 따라) |
| OS | Windows 10 / macOS 12 / Ubuntu 20.04 | 동일 |

### 설치 방법

**1. 저장소 클론 (또는 이미 있다면 해당 폴더로 이동)**

```bash
cd AudioSeparation
```

**2. 핵심 패키지 설치**

```bash
pip install -e .
```

**3. GUI 패키지 설치 (Gradio + Plotly)**

```bash
pip install -e ".[gui]"
```

**4. 전체 패키지 설치 (개발 포함)**

```bash
pip install -e ".[all]"
```

**설치 확인**

```bash
python -c "from simulator.simulator import Simulator; print('OK')"
python -c "import gradio; print('Gradio', gradio.__version__)"
```

---

## 2. 빠른 시작

### GUI로 씬 생성 (가장 쉬운 방법)

```bash
python app.py
```

브라우저에서 `http://localhost:7860` 접속 → Scene Editor 탭에서 파라미터 설정 → `▶ Generate Scene` 클릭

### 터미널에서 단일 씬 생성

```python
from simulator.if_modules.orchestration import simulate_scene
from simulator.uf.w151_config import SceneConfigValidator

config = SceneConfigValidator().validate({
    "scene_id": "my_scene_001",
    "seed": 42,
    "schema_version": "1.0.0",
    "room": {"type": "shoebox", "dimensions": {"L": 5.0, "W": 4.0, "H": 3.0}},
    "materials": {"default": "concrete"},
    "sources": [{"source_id": "s0", "position": [1.0, 1.5, 1.0]}],
    "receivers": [{"receiver_id": "r0", "position": [3.0, 1.5, 3.0]}],
    "sample_rate": 16000,
    "ism_order": 3,
    "output_dir": "output/my_scene",
})

result = simulate_scene(config)
print("RT60:", result["acoustic_summary"].rt60_measured_s, "s")
print("출력 폴더:", result["output_dir"])
```

### Facade 클래스로 씬 생성

```python
from simulator.simulator import Simulator

sim = Simulator(config_path="my_config.json", output_dir="output")
result = sim.run_single()
```

---

## 3. GUI 사용법

```
python app.py
# → http://localhost:7860
```

---

### Tab 1 — Scene Editor

단일 씬을 인터랙티브하게 설정하고 생성합니다.

#### 왼쪽 패널: 파라미터 설정

**Scene Settings**

| 항목 | 설명 | 기본값 |
|------|------|--------|
| Scene ID | 씬 고유 이름 (파일명에 사용됨) | `scene_001` |
| Random Seed | 재현 가능성을 위한 시드값 | `42` |

**Room Dimensions**

| 슬라이더 | 설명 | 범위 |
|----------|------|------|
| Length L (m) | 방 길이 (X축) | 1–20 m |
| Width W (m) | 방 너비 (Y축) | 1–20 m |
| Height H (m) | 방 높이 (Z축) | 1.5–10 m |

**Acoustic Settings**

| 항목 | 설명 | 권장값 |
|------|------|--------|
| Wall Material | 벽 재질 (RT60에 영향) | `concrete` |
| ISM Order | 반사 차수 (높을수록 정밀하지만 느림) | 3 |
| Sample Rate | 오디오 샘플레이트 (Hz) | `16000` |

**Sources (빨간 점)**

- Number of Sources: 음원 수 (1–3)
- S0/S1/S2: 각 음원의 X, Y, Z 좌표 (m)
- 좌표는 방 내부여야 함 (0 < X < L, 0 < Z < W, 0 < Y < H)

**Receivers (파란 다이아몬드)**

- Number of Receivers: 수음기(마이크) 수 (1–4)
- R0/R1/R2/R3: 각 수음기의 X, Y, Z 좌표 (m)

#### 오른쪽 패널: 3D 프리뷰 + 결과

**3D Room Preview**
- 마우스 드래그: 시점 회전
- 마우스 휠: 줌 인/아웃
- 파라미터 변경 시 실시간 자동 업데이트
- 빨간 구(●) = 음원, 파란 다이아몬드(◆) = 수음기

**Generate Scene 버튼**

`▶ Generate Scene` 클릭 시:
1. 씬 시뮬레이션 실행 (수 초 소요)
2. 오디오 플레이어에 수신기별 WAV 표시
3. 음향 요약 테이블 표시:
   - RT60 (잔향 시간, 단위: s)
   - DRR (직접-반향 비율, dB)
   - SNR (신호 대 잡음비, dB)
   - DOA Az/El (음원 방향각, 도)
   - 소요 시간 (s)

---

### Tab 2 — Batch Generator

여러 씬을 무작위 파라미터로 대량 생성합니다.

#### 설정 항목

| 항목 | 설명 | 예시 |
|------|------|------|
| Number of Scenes | 생성할 씬 수 | 100 |
| Seed Min/Max | 시드 범위 (각 씬은 이 범위에서 무작위 선택) | 0–9999 |
| L/W/H Min~Max | 방 크기 무작위 범위 (m) | L: 3–10, W: 3–8, H: 2.5–4 |
| ISM Order | 반사 차수 | 3 |
| Sample Rate | 샘플레이트 | 16000 |
| Output Directory | 출력 폴더 경로 | `output/batch` |

#### 실행

1. 파라미터 범위 입력
2. `▶ Start Batch` 클릭
3. 진행 테이블에서 각 씬의 상태 확인:
   - ✅ done: 성공
   - ❌ + 오류 메시지: 실패

> **팁:** 대량 생성 시 ISM Order를 낮추면(예: 2) 속도가 크게 향상됩니다.

---

### Tab 3 — Results Viewer

이전에 생성된 씬의 결과를 불러와 분석합니다.

1. `Upload scene_manifest.json` — 씬 폴더 내의 `scene_manifest.json` 파일 선택
2. `Load Manifest` 클릭
3. 결과 확인:
   - 수신기별 오디오 재생
   - 음향 요약 테이블
   - 전체 매니페스트 JSON

---

### Tab 4 — Config I/O

#### 설정 내보내기

1. Scene Editor에서 원하는 파라미터 설정
2. `⬇ Download Config as JSON` 클릭
3. JSON 파일 다운로드 + 프리뷰 표시

내보낸 JSON은 Python API나 다음 세션에서 그대로 재사용 가능.

#### 설정 불러오기

1. `Upload JSON Config` — 저장해둔 `.json` 또는 `.yaml` 파일 선택
2. `⬆ Load into Scene Editor` 클릭
3. Scene Editor 탭의 모든 값이 자동으로 채워짐

---

## 4. Python API 사용법

### 4-1. 단일 씬 생성

```python
from simulator.if_modules.orchestration import simulate_scene
from simulator.uf.w151_config import SceneConfigValidator

cfg = SceneConfigValidator().validate({
    "scene_id": "scene_001",
    "seed": 42,
    "schema_version": "1.0.0",
    "room": {
        "type": "shoebox",
        "dimensions": {"L": 6.0, "W": 5.0, "H": 3.0}
    },
    "materials": {"default": "carpet"},
    "sources": [
        {"source_id": "spk0", "position": [1.5, 1.5, 2.0]},
        {"source_id": "spk1", "position": [4.5, 1.5, 2.0]},
    ],
    "receivers": [
        {"receiver_id": "mic0", "position": [3.0, 1.5, 3.0]},
    ],
    "sample_rate": 16000,
    "ism_order": 3,
    "output_dir": "output/scene_001",
})

result = simulate_scene(cfg)

# 결과 접근
print(result["scene_id"])                         # "scene_001"
print(result["acoustic_summary"].rt60_measured_s) # 예: 0.42
print(result["acoustic_summary"].drr_db)          # 예: 5.2
print(result["output_dir"])                       # "output/scene_001"
print(result["manifest_path"])                    # .../scene_manifest.json
```

### 4-2. Facade로 YAML 파일 기반 실행

```python
from simulator.simulator import Simulator

sim = Simulator(config_path="configs/my_scene.yaml", output_dir="output")
result = sim.run_single()
```

### 4-3. 배치 생성

```python
from simulator.simulator import Simulator

sim = Simulator(config_path="configs/base_config.json", output_dir="output/batch")
summary = sim.run_batch(n_workers=4)  # 멀티프로세싱

print(f"완료: {summary.n_completed} / {summary.n_total}")
print(f"실패: {summary.n_failed}")
print(f"평균 RT60: {summary.mean_rt60_s:.3f} s")
```

### 4-4. 하위 모듈 직접 사용

```python
from simulator.uf.w122_reverberation import compute_image_sources, estimate_sabine_rt60
import numpy as np

# Sabine RT60 추정
rt60 = estimate_sabine_rt60(
    room_dims={"L": 5.0, "W": 4.0, "H": 3.0},
    material_map=None,  # None이면 기본값(concrete) 사용
)
print(f"Sabine RT60: {rt60:.3f} s")

# ISM 이미지 소스 열거
sources = compute_image_sources(
    room_dims={"L": 5.0, "W": 4.0, "H": 3.0},
    src_pos=np.array([1.0, 1.5, 1.0]),
    mic_pos=np.array([3.0, 1.5, 3.0]),
    ism_order=3,
)
print(f"이미지 소스 수: {len(sources)}")
```

---

## 5. 설정 파일(Config) 형식

### 최소 설정 (JSON)

```json
{
  "scene_id": "my_scene",
  "seed": 42,
  "schema_version": "1.0.0",
  "room": {
    "type": "shoebox",
    "dimensions": { "L": 5.0, "W": 4.0, "H": 3.0 }
  },
  "materials": { "default": "concrete" },
  "sources": [
    { "source_id": "s0", "position": [1.0, 1.5, 1.0] }
  ],
  "receivers": [
    { "receiver_id": "r0", "position": [3.0, 1.5, 3.0] }
  ]
}
```

### 전체 설정 옵션

```json
{
  "scene_id": "full_example",
  "seed": 1234,
  "schema_version": "1.0.0",
  "room": {
    "type": "shoebox",
    "dimensions": { "L": 8.0, "W": 6.0, "H": 3.5 }
  },
  "materials": {
    "default": "concrete",
    "floor": "carpet",
    "ceiling": "acoustic_tile"
  },
  "sources": [
    { "source_id": "spk0", "position": [1.5, 1.5, 2.0] },
    { "source_id": "spk1", "position": [6.0, 1.5, 4.0] }
  ],
  "receivers": [
    { "receiver_id": "mic0", "position": [4.0, 1.5, 3.0] },
    { "receiver_id": "mic1", "position": [4.2, 1.5, 3.0] }
  ],
  "motion": {
    "duration_s": 5.0,
    "source_motion_type": "linear",
    "receiver_motion_type": "static"
  },
  "impairments": {
    "noise_floor_db": -60,
    "packet_error_rate": 0.0,
    "bandwidth_hz": 7500
  },
  "sample_rate": 16000,
  "ism_order": 3,
  "speed_of_sound": 343.0,
  "output_dir": "output/full_example"
}
```

### YAML 형식

```yaml
scene_id: full_example
seed: 1234
schema_version: "1.0.0"
room:
  type: shoebox
  dimensions: { L: 8.0, W: 6.0, H: 3.5 }
materials:
  default: concrete
sources:
  - source_id: spk0
    position: [1.5, 1.5, 2.0]
receivers:
  - receiver_id: mic0
    position: [4.0, 1.5, 3.0]
sample_rate: 16000
ism_order: 3
output_dir: output/full_example
```

---

## 6. 출력 파일 구조

씬 생성 후 `output_dir/{scene_id}/` 폴더에 다음 파일이 생성됩니다:

```
output/
└── my_scene/
    ├── scene_manifest.json     ← 메타데이터 전체 (음향 파라미터, 파일 목록)
    ├── receiver_r0.wav         ← 수신기 r0의 처리된 오디오 (16bit PCM)
    ├── receiver_r1.wav         ← 수신기 r1의 오디오 (있는 경우)
    ├── source_s0_ref.wav       ← 음원 s0의 기준 신호 (클린)
    ├── rir_s0_r0.npy           ← s0→r0 RIR (numpy float32 배열)
    └── rir_s1_r0.npy           ← s1→r0 RIR (있는 경우)
```

### scene_manifest.json 구조

```json
{
  "schema_version": "1.0",
  "scene_id": "my_scene",
  "seed": 42,
  "created_at": "2026-03-21T10:00:00",
  "room": { "type": "shoebox", "dimensions": {...} },
  "sources": [...],
  "receivers": [...],
  "acoustic_summary": {
    "rt60_measured_s": 0.42,
    "drr_db": 5.2,
    "snr_db": 38.5,
    "doa_az_deg": 135.0,
    "doa_el_deg": 0.0
  },
  "audio_files": [
    "output/my_scene/receiver_r0.wav"
  ],
  "rir_files": [
    "output/my_scene/rir_s0_r0.npy"
  ]
}
```

---

## 7. 주요 파라미터 레퍼런스

### 재질(Material) 종류별 RT60 영향

| 재질 | 특성 | 예상 RT60 (5×4×3 m) |
|------|------|---------------------|
| `concrete` | 매우 반사적 | ~0.8–1.2 s |
| `brick` | 반사적 | ~0.6–1.0 s |
| `wood` | 중간 | ~0.4–0.7 s |
| `glass` | 매우 반사적 | ~0.8–1.5 s |
| `carpet` | 흡음 | ~0.2–0.4 s |
| `acoustic_tile` | 매우 흡음 | ~0.1–0.3 s |
| `default` | 중간 (α=0.5) | ~0.2–0.5 s |

### ISM Order와 정밀도/속도 트레이드오프

| ISM Order | 이미지 소스 수 (3×4×5 m) | 근사 소요시간 | 추천 용도 |
|-----------|--------------------------|--------------|-----------|
| 1 | 6 | 매우 빠름 | 테스트, 프리뷰 |
| 2 | 18 | 빠름 | 간단한 환경 |
| 3 | 38 | 보통 | **일반 데이터셋** |
| 5 | ~100 | 느림 | 고정밀 RIR |
| 8+ | ~400+ | 매우 느림 | 연구용 |

### 유효한 샘플레이트

`8000`, `16000`, `22050`, `44100`, `48000` Hz

---

## 8. 테스트 실행

### 전체 테스트 (권장)

```bash
python -m pytest tests/ -v
```

### 특정 모듈 테스트

```bash
# W122 잔향 모델 테스트
python -m pytest tests/unit/test_w122_reverberation.py -v

# 통합 테스트만
python -m pytest tests/integration/ -v
```

### 커버리지 포함

```bash
python -m pytest tests/ --cov=simulator --cov-report=html
# → htmlcov/index.html 확인
```

### 핵심 기능 스모크 테스트

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from simulator.uf.w111_room_geometry import define_room_primitive
room = define_room_primitive({'type':'shoebox','dimensions':{'L':5,'W':4,'H':3}})
print('Room volume:', room.aabb.volume_m3, 'm3')

from simulator.uf.w121_direct_path import compute_distance_and_delay
import numpy as np
r = compute_distance_and_delay(np.zeros(3), np.array([1.,0.,0.]), 16000)
print('1m delay:', r['delay_samples'], 'samples')

from simulator.uf.w122_reverberation import compute_image_sources
imgs = compute_image_sources({'L':5,'W':4,'H':3}, np.array([1.,1.,1.]), np.array([3.,1.,3.]), ism_order=1)
print('ISM order=1 sources:', len(imgs), '(expected 6)')
"
```

기대 출력:
```
Room volume: 60.0 m3
1m delay: 47 samples
ISM order=1 sources: 6 (expected 6)
```

---

## 9. 자주 묻는 질문 (FAQ)

**Q. RT60이 너무 길게 나옵니다.**

A. `materials`에 흡음 재질을 사용하세요. `carpet`이나 `acoustic_tile`은 RT60을 크게 줄입니다. 또는 방 크기를 줄이거나 흡음 재질의 벽 면적을 늘리세요.

---

**Q. 음원/수음기 좌표가 방 밖으로 나갔을 때 어떻게 됩니까?**

A. `SceneConfigValidator`가 검증 오류를 반환합니다. 좌표는 반드시 방 내부여야 합니다:
- `0 < X < L`, `0 < Y < H`, `0 < Z < W`
- 벽에서 최소 0.1 m 이상 떨어지길 권장합니다.

---

**Q. WAV 파일에 아무 소리가 없습니다.**

A. 현재 V1은 화이트 노이즈를 소스 신호로 사용합니다. 실제 음성 파일을 입력하려면 `simulate_scene()` 호출 전에 `source_signals` 인자를 직접 전달해야 합니다 (API 직접 사용 시).

---

**Q. 배치 생성이 너무 느립니다.**

A. 다음을 시도하세요:
1. ISM Order를 2–3으로 낮추기
2. Worker 수 늘리기 (`n_workers=8`)
3. Sample Rate를 16000 Hz로 유지 (44100은 4배 느림)
4. 씬당 음원/수음기 수 줄이기

---

**Q. `ModuleNotFoundError: No module named 'simulator'`**

A. `src/` 디렉토리가 Python 경로에 없습니다:
```bash
# 방법 1: editable install (권장)
pip install -e .

# 방법 2: 경로 수동 추가
import sys; sys.path.insert(0, 'src')
```

---

**Q. Gradio가 설치되어 있는데 app.py가 실행이 안 됩니다.**

A. Gradio 버전을 확인하세요:
```bash
python -c "import gradio; print(gradio.__version__)"
# 4.0 이상이어야 합니다
pip install "gradio>=4.0" --upgrade
```

---

**Q. 같은 seed로 실행했는데 결과가 다릅니다.**

A. ISM과 재질 계산은 결정론적입니다. 단, `motion` 파라미터가 있는 동적 씬에서는 타임라인 생성이 내부 부동소수점 연산에 따라 미세하게 달라질 수 있습니다. 완전한 재현을 위해 `seed`와 함께 `motion` 없이 static 씬을 사용하세요.

---

## 10. 알려진 제한사항

| 번호 | 제한사항 | 해결 예정 버전 |
|------|----------|---------------|
| L-01 | 바이노럴 렌더링(BRIR)은 합성 HRTF 사용 (CIPIC DB 미연동) | v1.1 |
| L-02 | 동적 씬의 RIR은 1/r 임펄스 근사 (완전 ISM 아님) | v1.1 |
| L-03 | Mesh 방 (OBJ/STL)은 파싱만 가능, ISM 미지원 | v1.2 |
| L-04 | 실제 음성 파일 입력 미지원 (GUI에서) | v1.1 |
| L-05 | GPU 가속 없음 (CPU만 사용) | v1.2 |
| L-06 | 다중 음원 믹싱 파이프라인 없음 | v1.2 |

---

## 부록: 재질별 흡음 계수 (125–4000 Hz 옥타브밴드)

| 재질 | 125 Hz | 250 Hz | 500 Hz | 1000 Hz | 2000 Hz | 4000 Hz |
|------|--------|--------|--------|---------|---------|---------|
| concrete | 0.01 | 0.02 | 0.02 | 0.03 | 0.03 | 0.04 |
| brick | 0.03 | 0.03 | 0.03 | 0.04 | 0.05 | 0.07 |
| carpet | 0.08 | 0.24 | 0.57 | 0.69 | 0.71 | 0.73 |
| glass | 0.35 | 0.25 | 0.18 | 0.12 | 0.07 | 0.04 |
| wood | 0.15 | 0.11 | 0.10 | 0.07 | 0.06 | 0.07 |
| acoustic_tile | 0.20 | 0.45 | 0.81 | 0.90 | 0.87 | 0.87 |

> 출처: Architectural Acoustics Illustrated (Ermann, 2015)

---

*문의사항은 GitHub Issues 또는 프로젝트 설계 문서(`W100000/` 폴더)를 참조하세요.*
