# W100000 Spatial Audio Generator — 사용 매뉴얼

> 버전: 1.1.0 | 최종 수정: 2026-03-23

---

## 목차

1. [설치](#1-설치)
2. [빠른 시작](#2-빠른-시작)
3. [GUI 사용법](#3-gui-사용법)
   - [Tab 1 — Scene Editor](#tab-1--scene-editor)
   - [Tab 2 — Batch Generator](#tab-2--batch-generator)
   - [Tab 3 — Results Viewer](#tab-3--results-viewer)
   - [Tab 4 — Config I/O](#tab-4--config-io)
   - [Tab 5 — Zoom Scenario](#tab-5--zoom-scenario)
   - [Tab 6 — Run from Files](#tab-6--run-from-files)
4. [실전 사용 예시: JSON 작성 → 시뮬레이션 전 과정](#4-실전-사용-예시)
5. [Python API 사용법](#5-python-api-사용법)
6. [설정 파일(Config) 형식](#6-설정-파일config-형식)
7. [출력 파일 구조](#7-출력-파일-구조)
8. [주요 파라미터 레퍼런스](#8-주요-파라미터-레퍼런스)
9. [테스트 실행](#9-테스트-실행)
10. [자주 묻는 질문 (FAQ)](#10-자주-묻는-질문-faq)
11. [알려진 제한사항](#11-알려진-제한사항)

---

## 1. 설치

### 시스템 요구사항

| 항목 | 최소 사양 | 권장 사양 |
|------|-----------|-----------|
| Python | 3.9+ | 3.13 |
| RAM | 4 GB | 16 GB |
| 저장공간 | 2 GB | 20 GB+ |
| OS | Windows 10 / macOS 12 / Ubuntu 20.04 | 동일 |

### 설치 방법

```bash
# 1. 저장소 클론 후 프로젝트 폴더로 이동
cd AudioSeparation

# 2. 핵심 패키지 설치
pip install -e .

# 3. GUI 패키지 추가 설치 (Gradio + Plotly)
pip install -e ".[gui]"

# 4. 전체 패키지 (개발 포함)
pip install -e ".[all]"
```

**설치 확인**

```bash
python -c "from simulator.simulator import Simulator; print('Core OK')"
python -c "import gradio; print('Gradio', gradio.__version__)"
python -c "import plotly; print('Plotly', plotly.__version__)"
```

---

## 2. 빠른 시작

### GUI 실행 (가장 쉬운 방법)

```bash
python app.py
# → 브라우저에서 http://localhost:7860 접속
```

### 터미널 — 단일 씬 1분 완성

```python
import sys; sys.path.insert(0, 'src')
from simulator.scenarios.zoom_meeting import generate_zoom_scenario, save_scenarios
from simulator.uf.w151_config import SceneConfigValidator
from simulator.if_modules.orchestration import simulate_scene

# 1. 씬 생성
cfg_dict = generate_zoom_scenario(n_participants=4, seed=42)

# 2. 검증
cfg = SceneConfigValidator().validate({k:v for k,v in cfg_dict.items() if k != '_zoom_meta'})

# 3. 시뮬레이션
result = simulate_scene(cfg)
print("RT60:", result["acoustic_summary"].rt60_measured_s, "s")
print("출력:", result["output_dir"])
```

---

## 3. GUI 사용법

```bash
python app.py   # → http://localhost:7860
```

---

### Tab 1 — Scene Editor

단일 씬을 인터랙티브하게 설정하고 생성합니다.

#### 왼쪽 패널: 파라미터 설정

| 항목 | 설명 | 기본값 |
|------|------|--------|
| Scene ID | 씬 고유 이름 | `scene_001` |
| Random Seed | 재현성을 위한 시드 | `42` |
| Length/Width/Height | 방 크기 (m) | 5 / 4 / 3 |
| Wall Material | 벽 재질 (RT60에 영향) | `concrete` |
| ISM Order | 반사 차수 | `3` |
| Sample Rate | 오디오 샘플레이트 (Hz) | `16000` |
| Sources (S0~S2) | 각 음원 XYZ 좌표 | — |
| Receivers (R0~R3) | 각 수음기 XYZ 좌표 | — |

#### 오른쪽 패널: 3D 프리뷰 + 결과

- **3D Room Preview**: 마우스 드래그(회전), 휠(줌), 파라미터 변경 시 실시간 업데이트
  - 빨간 구(●) = 음원 / 파란 다이아몬드(◆) = 수음기
- `▶ Generate Scene` 클릭 → WAV 재생, 음향 요약(RT60·DRR·SNR·DOA) 표시

---

### Tab 2 — Batch Generator

랜덤 파라미터로 씬을 대량 생성합니다.

| 항목 | 설명 |
|------|------|
| Number of Scenes | 생성 씬 수 |
| Seed Min/Max | 시드 범위 |
| L/W/H Min~Max | 방 크기 무작위 범위 (m) |
| Output Directory | 출력 폴더 (`output/batch`) |

`▶ Start Batch` 클릭 → 진행 테이블에 scene_id / 상태 / 소요시간 / RT60 표시

> **팁:** 대량 생성 시 ISM Order를 2로 낮추면 속도 3배 향상

---

### Tab 3 — Results Viewer

이전 생성 결과를 불러와 분석합니다.

1. `Upload scene_manifest.json` → `Load Manifest` 클릭
2. 수신기별 오디오 재생 + 음향 요약 + 전체 JSON 확인

---

### Tab 4 — Config I/O

**내보내기:** Scene Editor 파라미터 → JSON 파일 다운로드
**불러오기:** JSON/YAML 파일 업로드 → Scene Editor 자동 반영

---

### Tab 5 — Zoom Scenario

Zoom 화상 미팅 씬을 물리적으로 정확하게 자동 생성합니다.

#### 파라미터

| 항목 | 설명 | 기본값 |
|------|------|--------|
| Participants | 참여자 수 (2–12) | `4` |
| Room Size | 방 크기 프리셋 (auto/small/medium/large) | `auto` |
| Wall Material | 벽 재질 | `concrete` |
| Include TV | TV를 반사 장애물로 추가 | ✅ |
| TV as sound source | TV 스피커를 음원으로 추가 | ☐ |
| ISM Order / Sample Rate / Seed | 시뮬레이션 파라미터 | 3 / 16000 / 42 |
| # Scenarios | 저장할 시나리오 수 | `10` |
| Output Directory | JSON 저장 폴더 | `output/scenarios` |

#### 자동 생성 레이아웃

```
       [TV 📺]  [카메라 🎤]       ← X=0 벽
  ┌──────────────────────────────┐
  │  ●    ●    ●    (앞줄 참여자) │
  │  ═════ 테이블 ═════           │
  │  ●    ●    ●    (뒷줄 참여자) │
  └──────────────────────────────┘
  (Y) 높이: 입 1.18m, TV 중심 1.5m
```

- **앞줄**: Z = 테이블중심 − 테이블너비/2 − 0.3 m (TV 방향을 마주봄)
- **뒷줄**: Z = 테이블중심 + 테이블너비/2 + 0.3 m
- **Conference Mic**: 테이블 상면 중앙 (Y = 테이블높이 + 0.05 m)
- **TV**: X=0 벽, 중심 Y=1.5 m, acoustic_role="reflective"

#### 사용 방법

1. 파라미터 설정 → 슬라이더 변경 시 **3D 프리뷰 자동 업데이트**
2. `🎲 Preview` — 1개 시나리오 미리보기 (JSON 프리뷰 + 3D 뷰 동시 갱신)
3. `📁 Generate & Save N` — N개 시나리오를 JSON으로 저장, 파일 목록 표시

---

### Tab 6 — Run from Files

저장된 시나리오 JSON 파일을 선택해 배치 시뮬레이션을 실행합니다.

1. **Select Scenario JSON Files** — OS 파일 다이얼로그로 `.json` 다중 선택 (Ctrl+클릭)
2. Output Directory 설정 (`output/results`)
3. `▶ Simulate Selected Files` 클릭
4. 진행 테이블에서 실시간 확인 (scene_id / ✅ done or ❌ error / 소요시간 / RT60)

> **팁:** Tab 5에서 생성한 `output/scenarios/*.json` 파일을 여기서 바로 선택해 실행하면 됩니다.

---

## 4. 실전 사용 예시

### 전체 워크플로: Zoom 씬 JSON 작성 → 시뮬레이션 → 결과 확인

다음 예시는 **4인 Zoom 미팅 씬 10개를 생성**하고, 그 중 **선택한 파일을 시뮬레이션**해 데이터를 얻는 전 과정을 보여줍니다.

---

#### 방법 A — GUI (권장, 코딩 없음)

```
1. python app.py 실행 → http://localhost:7860

2. [Tab 5: Zoom Scenario] 탭으로 이동
   - Participants: 4
   - Room Size: auto
   - Material: concrete
   - Include TV: ✅
   - TV as sound source: ☐  (TV 반향만 모델링, 음원은 사람만)
   - ISM Order: 3
   - # Scenarios: 10
   - Output Directory: output/zoom_sessions
   → [📁 Generate & Save 10] 클릭
   → output/zoom_sessions/ 에 JSON 10개 저장됨

3. [Tab 6: Run from Files] 탭으로 이동
   - Select Scenario JSON Files → output/zoom_sessions/ 에서 원하는 파일 선택
   - Output Directory: output/results
   → [▶ Simulate Selected Files] 클릭
   → 진행 테이블에서 완료 확인

4. [Tab 3: Results Viewer] 탭으로 이동
   - output/results/zoom_000042_n4/scene_manifest.json 업로드
   → 오디오 재생 + RT60/DRR/SNR 확인
```

---

#### 방법 B — Python 스크립트

아래 스크립트 하나로 **시나리오 생성 → JSON 저장 → 시뮬레이션 → 결과 출력** 전 과정을 실행합니다.

```python
"""
end_to_end_example.py
Zoom 4인 씬 5개를 생성하고 시뮬레이션하는 완전한 예시
"""
import sys, os, json
sys.path.insert(0, 'src')

from simulator.scenarios.zoom_meeting import (
    generate_zoom_scenarios,
    save_scenarios,
    load_scenario_from_file,
)
from simulator.uf.w151_config import SceneConfigValidator
from simulator.if_modules.orchestration import simulate_scene

# ── Step 1: 시나리오 딕셔너리 생성 ──────────────────────────────────────────
print("=== Step 1: 시나리오 생성 ===")
scenarios = generate_zoom_scenarios(
    n_scenarios=5,
    min_participants=3,
    max_participants=6,
    seed_base=0,
    output_dir="output/zoom_results",  # 시뮬레이션 결과가 여기로 저장됨
    material="concrete",
    has_tv=True,
    tv_as_source=False,  # TV는 반사 장애물로만 사용
    sample_rate=16000,
    ism_order=3,
)
for i, s in enumerate(scenarios):
    meta = s["_zoom_meta"]
    dims = s["room"]["dimensions"]
    print(f"  씬 {i}: {s['scene_id']}, {meta['n_participants']}명, "
          f"방 {dims['L']}x{dims['W']}x{dims['H']}m, "
          f"장애물 {len(s['room']['obstacles'])}개")

# ── Step 2: JSON 파일로 저장 ─────────────────────────────────────────────────
print("\n=== Step 2: JSON 저장 ===")
json_dir = "output/zoom_scenarios"
paths = save_scenarios(scenarios, json_dir)
for p in paths:
    print(f"  저장됨: {os.path.basename(p)}")

# ── Step 3: 저장된 JSON 로드 → 검증 → 시뮬레이션 ────────────────────────────
print("\n=== Step 3: 시뮬레이션 ===")
results = []
for path in paths:
    # 파일 로드
    raw = load_scenario_from_file(path)

    # _zoom_meta는 시뮬레이터 내부 키가 아니므로 제거
    raw.pop("_zoom_meta", None)

    # SceneConfig 검증
    try:
        cfg = SceneConfigValidator().validate(raw)
    except Exception as e:
        print(f"  [SKIP] {raw.get('scene_id', '?')}: 검증 실패 — {e}")
        continue

    # 시뮬레이션 실행
    result = simulate_scene(cfg)
    summary = result["acoustic_summary"]
    results.append(result)

    print(f"  {cfg.scene_id}: "
          f"RT60={summary.rt60_measured_s:.3f}s, "
          f"DRR={summary.drr_db:.1f}dB, "
          f"SNR={summary.snr_db:.1f}dB  "
          f"({result['elapsed_s']:.1f}s 소요)")

# ── Step 4: 결과 요약 ────────────────────────────────────────────────────────
print("\n=== Step 4: 결과 요약 ===")
print(f"완료: {len(results)}/{len(paths)} 씬")
if results:
    rt60_list = [r["acoustic_summary"].rt60_measured_s for r in results]
    print(f"RT60 범위: {min(rt60_list):.3f}s ~ {max(rt60_list):.3f}s")
    print(f"출력 폴더: {results[0]['output_dir']} ...")

    # manifest 내용 확인
    manifest_path = results[0]["manifest_path"]
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    print(f"\n첫 번째 씬 manifest ({os.path.basename(manifest_path)}):")
    print(f"  audio_files: {[os.path.basename(p) for p in manifest.get('audio_files', [])]}")
    print(f"  rir_files:   {[os.path.basename(p) for p in manifest.get('rir_files', [])]}")
```

**실행:**
```bash
python end_to_end_example.py
```

**예상 출력:**
```
=== Step 1: 시나리오 생성 ===
  씬 0: zoom_000000_n5, 5명, 방 9.0x5.0x3.0m, 장애물 8개
  씬 1: zoom_000001_n4, 4명, 방 6.0x4.0x2.8m, 장애물 7개
  씬 2: zoom_000002_n3, 3명, 방 6.0x4.0x2.8m, 장애물 6개
  씬 3: zoom_000003_n6, 6명, 방 9.0x5.0x3.0m, 장애물 9개
  씬 4: zoom_000004_n5, 5명, 방 9.0x5.0x3.0m, 장애물 8개

=== Step 2: JSON 저장 ===
  저장됨: zoom_000000_n5.json
  저장됨: zoom_000001_n4.json
  ...

=== Step 3: 시뮬레이션 ===
  zoom_000000_n5: RT60=0.381s, DRR=6.2dB, SNR=38.1dB  (4.3s 소요)
  zoom_000001_n4: RT60=0.312s, DRR=7.5dB, SNR=38.4dB  (3.1s 소요)
  ...

=== Step 4: 결과 요약 ===
완료: 5/5 씬
RT60 범위: 0.312s ~ 0.421s
출력 폴더: output/zoom_results/zoom_000000_n5 ...

첫 번째 씬 manifest (scene_manifest.json):
  audio_files: ['receiver_conf_mic.wav']
  rir_files:   ['rir_person_0_conf_mic.wav', 'rir_person_1_conf_mic.wav', ...]
```

---

#### 방법 C — JSON 직접 작성 후 시뮬레이션

Zoom 씬 시나리오 JSON을 직접 작성하거나 편집하고 싶을 때 사용합니다.

**zoom_4p_concrete.json** (4인, 콘크리트 방, TV 포함):

```json
{
  "scene_id": "zoom_meeting_4p",
  "seed": 42,
  "schema_version": "1.0.0",
  "room": {
    "type": "shoebox",
    "dimensions": { "L": 6.0, "W": 4.0, "H": 2.8 },
    "obstacles": [
      {
        "type": "table",
        "size": [2.0, 0.75, 0.9],
        "position": [3.0, 0.375, 2.0],
        "acoustic_role": "reflective"
      },
      {
        "type": "chair",
        "size": [0.5, 0.9, 0.5],
        "position": [2.0, 0.45, 0.85],
        "acoustic_role": "absorptive"
      },
      {
        "type": "chair",
        "size": [0.5, 0.9, 0.5],
        "position": [4.0, 0.45, 0.85],
        "acoustic_role": "absorptive"
      },
      {
        "type": "chair",
        "size": [0.5, 0.9, 0.5],
        "position": [2.0, 0.45, 3.15],
        "acoustic_role": "absorptive"
      },
      {
        "type": "chair",
        "size": [0.5, 0.9, 0.5],
        "position": [4.0, 0.45, 3.15],
        "acoustic_role": "absorptive"
      },
      {
        "type": "tv",
        "size": [0.1, 0.81, 1.44],
        "position": [0.05, 1.5, 2.0],
        "acoustic_role": "reflective"
      }
    ]
  },
  "materials": { "default": "concrete" },
  "sources": [
    { "source_id": "person_0", "position": [2.0, 1.18, 0.85] },
    { "source_id": "person_1", "position": [4.0, 1.18, 0.85] },
    { "source_id": "person_2", "position": [2.0, 1.18, 3.15] },
    { "source_id": "person_3", "position": [4.0, 1.18, 3.15] }
  ],
  "receivers": [
    { "receiver_id": "conf_mic", "position": [3.0, 0.8, 2.0] }
  ],
  "sample_rate": 16000,
  "ism_order": 3,
  "output_dir": "output/zoom_4p_concrete"
}
```

**시뮬레이션 실행:**

```bash
# Python 한 줄로 실행
python -c "
import sys; sys.path.insert(0, 'src')
from simulator.uf.w151_config import SceneConfigValidator
from simulator.if_modules.orchestration import simulate_scene
import json

with open('zoom_4p_concrete.json', encoding='utf-8') as f:
    raw = json.load(f)

cfg = SceneConfigValidator().validate(raw)
result = simulate_scene(cfg)
s = result['acoustic_summary']
print(f'RT60={s.rt60_measured_s:.3f}s  DRR={s.drr_db:.1f}dB  SNR={s.snr_db:.1f}dB')
print('출력:', result['output_dir'])
"
```

또는 **Tab 6 — Run from Files** 에서 `zoom_4p_concrete.json` 파일을 업로드해서 실행해도 됩니다.

---

#### 방법 D — 랜덤 시나리오 대량 생성 (데이터셋 수집)

다양한 참여자 수·방 크기·재질 조합으로 1000개 씬을 생성합니다.

```python
import sys; sys.path.insert(0, 'src')
from simulator.scenarios.zoom_meeting import generate_zoom_scenarios, save_scenarios

# 1000개 생성: 2~8인, 다양한 재질
scenarios = generate_zoom_scenarios(
    n_scenarios=1000,
    min_participants=2,
    max_participants=8,
    seed_base=0,
    output_dir="output/dataset_zoom",
    has_tv=True,
    sample_rate=16000,
    ism_order=3,
)

# JSON 저장
paths = save_scenarios(scenarios, "output/zoom_json_1000")
print(f"{len(paths)}개 시나리오 저장 완료")
```

생성된 JSON 파일들을 **Tab 6 — Run from Files** 에서 일괄 선택해 시뮬레이션할 수 있습니다.

---

## 5. Python API 사용법

### 5-1. Zoom 시나리오 API

```python
from simulator.scenarios.zoom_meeting import (
    generate_zoom_scenario,
    generate_zoom_scenarios,
    save_scenarios,
    load_scenario_from_file,
)

# 단일 시나리오
cfg = generate_zoom_scenario(
    n_participants=6,
    seed=123,
    room_size="medium",      # "auto", "small", "medium", "large"
    material="wood",
    has_tv=True,
    tv_as_source=True,       # TV 스피커를 음원으로 추가
    sample_rate=16000,
    ism_order=3,
)

# 배치 생성
configs = generate_zoom_scenarios(
    n_scenarios=50,
    min_participants=2,
    max_participants=10,
    seed_base=1000,
)
paths = save_scenarios(configs, "output/my_scenarios")
```

### 5-2. 단일 씬 직접 생성

```python
from simulator.if_modules.orchestration import simulate_scene
from simulator.uf.w151_config import SceneConfigValidator

cfg = SceneConfigValidator().validate({
    "scene_id": "meeting_001",
    "seed": 42,
    "schema_version": "1.0.0",
    "room": {"type": "shoebox", "dimensions": {"L": 6.0, "W": 4.0, "H": 3.0}},
    "materials": {"default": "carpet"},
    "sources": [
        {"source_id": "spk0", "position": [1.5, 1.5, 1.5]},
        {"source_id": "spk1", "position": [4.0, 1.5, 2.5]},
    ],
    "receivers": [{"receiver_id": "mic0", "position": [3.0, 1.2, 2.0]}],
    "sample_rate": 16000,
    "ism_order": 3,
    "output_dir": "output/meeting_001",
})

result = simulate_scene(cfg)
print(result["acoustic_summary"].rt60_measured_s)  # 0.42
```

### 5-3. Facade 클래스로 YAML 기반 실행

```python
from simulator.simulator import Simulator

sim = Simulator(config_path="configs/my_scene.yaml", output_dir="output")
result = sim.run_single()
```

### 5-4. 하위 모듈 직접 사용

```python
from simulator.uf.w122_reverberation import compute_image_sources, estimate_sabine_rt60
import numpy as np

rt60 = estimate_sabine_rt60({"L": 6.0, "W": 4.0, "H": 2.8})
print(f"Sabine RT60: {rt60:.3f} s")

sources = compute_image_sources(
    room_dims={"L": 6.0, "W": 4.0, "H": 2.8},
    src_pos=np.array([2.0, 1.18, 0.85]),
    mic_pos=np.array([3.0, 0.80, 2.0]),
    ism_order=3,
)
print(f"이미지 소스 수: {len(sources)}")
```

---

## 6. 설정 파일(Config) 형식

### 최소 설정

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
  "sources": [{ "source_id": "s0", "position": [1.0, 1.5, 1.0] }],
  "receivers": [{ "receiver_id": "r0", "position": [3.0, 1.5, 3.0] }]
}
```

### 장애물 포함 설정 (Zoom 회의실 패턴)

```json
{
  "scene_id": "zoom_custom",
  "seed": 100,
  "schema_version": "1.0.0",
  "room": {
    "type": "shoebox",
    "dimensions": { "L": 9.0, "W": 5.0, "H": 3.0 },
    "obstacles": [
      {
        "type": "table",
        "size": [3.0, 0.75, 1.1],
        "position": [4.5, 0.375, 2.5],
        "acoustic_role": "reflective"
      },
      {
        "type": "tv",
        "size": [0.1, 0.81, 1.44],
        "position": [0.05, 1.5, 2.5],
        "acoustic_role": "reflective"
      },
      {
        "type": "chair",
        "size": [0.5, 0.9, 0.5],
        "position": [3.0, 0.45, 1.1],
        "acoustic_role": "absorptive"
      }
    ]
  },
  "materials": {
    "default": "concrete",
    "floor": "carpet"
  },
  "sources": [
    { "source_id": "person_0", "position": [3.0, 1.18, 1.1] },
    { "source_id": "person_1", "position": [6.0, 1.18, 1.1] }
  ],
  "receivers": [
    { "receiver_id": "conf_mic", "position": [4.5, 0.8, 2.5] }
  ],
  "sample_rate": 16000,
  "ism_order": 3,
  "output_dir": "output/zoom_custom"
}
```

### 장애물 위치 지정 규칙

| 필드 | 설명 |
|------|------|
| `type` | 오브젝트 타입 (`table`, `chair`, `tv`, `partition`, `monitor`, `whiteboard`, `laptop`) |
| `size` | `[X크기, Y크기, Z크기]` (m), 바운딩박스 |
| `position` | `[X, Y, Z]` (m), 오브젝트 중심 좌표. **지정하면 rejection sampling 건너뜀** |
| `acoustic_role` | `"reflective"` / `"absorptive"` / `"occluding"` (생략 시 타입별 기본값) |
| `rotation_y` | Y축 회전각 (rad), 기본값 0 |

### 장애물 타입별 기본 acoustic_role

| 타입 | 기본 역할 | 음향 효과 |
|------|----------|-----------|
| `table` | reflective | 반사 (RT60 증가) |
| `tv`, `monitor`, `whiteboard`, `laptop` | reflective | 반사 |
| `chair` | absorptive | 흡음 (RT60 감소) |
| `partition` | occluding | 차폐 (직접파 차단) |

### YAML 형식

```yaml
scene_id: zoom_yaml_example
seed: 42
schema_version: "1.0.0"
room:
  type: shoebox
  dimensions: { L: 6.0, W: 4.0, H: 2.8 }
materials:
  default: concrete
sources:
  - source_id: person_0
    position: [2.0, 1.18, 0.85]
receivers:
  - receiver_id: conf_mic
    position: [3.0, 0.8, 2.0]
sample_rate: 16000
ism_order: 3
```

---

## 7. 출력 파일 구조

> 2026-11-21 변경: 감사 개선 설계([W1_audit_remediation_design.md](design_md/W100000/W1_audit_remediation_design.md))에 따라 파일 이름, 인코딩, 매니페스트 스키마가 바뀌었다. 이전 `receiver_*.wav`, `source_*_clean.wav`, `rir_{src}_{rec}.wav`는 더 이상 만들지 않는다.

```
output/
├── batch_checkpoint.json            ← 배치 재개 정보 (schema 2, 작업 지문 포함)
├── _quarantine/<scene_id>/          ← QC 실패 씬 (qc_failure.json에 이유)
└── zoom_meeting_4p/                 ← {output_dir}/{scene_id}/  (QC 통과 후 원자적으로 확정)
    ├── scene_manifest.json          ← schema 2.0.0 메타데이터
    ├── mixture__conf_mic.wav        ← 관측 혼합음 (수음 체인 적용 후)
    ├── noise__conf_mic.wav          ← 혼합음에 더해진 장치 잡음
    ├── reference__person_0__conf_mic.wav  ← 분리 정답: 마이크 위치의 음원 이미지 (장치 열화 전)
    ├── dry__person_0.wav            ← 씬 타임라인에 놓인 건조 신호
    ├── rir__person_0__conf_mic.wav  ← RIR
    ├── params.json                  ← 해석된(기본값이 채워진) 설정
    └── acoustic_summary.json
```

* 모든 WAV는 **IEEE float32**다. `scipy.io.wavfile.read`, `soundfile.read`로 읽는다(표준 `wave` 모듈은 float WAV를 읽지 못한다).
* 혼합음·참조·잡음은 같은 샘플 격자를 쓴다. 인덱스 0이 씬 시작이고, 길이 `T = round(duration_s·fs) + RIR 길이 − 1`이다(`render.tail: "trim"`이면 `duration_s·fs`).
* 장치 열화 전에는 `Σ reference == mixture − noise`가 성립한다(클리핑·코덱이 없을 때).
* 매니페스트의 경로는 **출력 루트 기준 상대 경로**(`<scene_id>/<file>`)다. 폴더를 옮겨도 그대로 읽힌다.

### scene_manifest.json 주요 필드 (schema 2.0.0)

| 필드 | 내용 |
| --- | --- |
| `fingerprint` | 작업 지문. 표시 ID·출력 폴더와 무관하고, 시드·기하·장치·입력 파일 해시가 바뀌면 달라진다 |
| `render` | `profile`(static_v1), `fs`, `n_samples`, `reference_receiver`, `approximations` |
| `sources[]` | `onset_sample`, `n_samples`, `truncated`, 신호 출처(`kind`, `sha256`, `resampled_from`) |
| `receivers[]` | 명목·유효 좌표, `clock_shift_samples`, 장치 파라미터 |
| `geometry.pairs[]` | 쌍별 거리, 직접파 지연, DOA, 도달 구간, RT60/DRR |
| `labels` | 기준 채널의 활성 구간, `overlap_ratio`, 음원별 `snr_db`와 정의 |
| `files[]` | 경로, 역할, 샘플 수, `sha256`, 바이트 수 |
| `qc` | `passed`, 검사별 결과, 플래그(클리핑·헤드룸 등) |
| `audio_files`, `rir_files`, `acoustic_summary` | v1 호환 필드 |

### 학습 코드에서 읽기

```python
import sys; sys.path.insert(0, "src")
from datatools.loader import load_scene
b = load_scene("output/zoom_meeting_4p/scene_manifest.json")   # 체크섬·모양·QC 검증
b.mixture      # float32 [C, T]
b.references   # float32 [S, C, T]
b.noise        # float32 [C, T]
```

### 새 설정 필드 (선택)

| 위치 | 필드 | 설명 |
| --- | --- | --- |
| `sources[i]` | `signal_path`, `onset_s`, `level_dbfs` | 건조 음성 WAV(다른 샘플레이트는 자동 변환), 시작 시각, 활성 RMS 레벨 |
| `receivers[i]` | `gain_db`, `noise_floor_dbfs`, `clip_threshold_dbfs`, `sensitivity_db` | **채널별** 장치 파라미터 |
| `impairments.array_errors` | `position_sigma_m`, `max_clock_skew_samples` | 전파 전 위치 오차, 채널 시계 시프트 |
| `render` | `tail`, `allow_static_approximation` | 잔향 꼬리 유지/자르기, 이동 엔터티를 첫 틱으로 근사 |
| `qc` | `fail_on_clip` | 클리핑을 실패로 처리 |
| 최상위 | `reference_receiver` | 라벨·SNR 기준 채널 (기본: 첫 수음기) |

지원 범위는 `static_v1`이다. 이동 음원·수음기, `omni`가 아닌 지향성, 바이노럴은 렌더 전에 `UnsupportedProfileError`로 거부한다. ID는 영문·숫자·`.`·`-`·단일 `_`만 쓸 수 있고 씬 안에서 고유해야 한다.

---

## 8. 주요 파라미터 레퍼런스

### 재질별 RT60 영향 (방 크기 6×4×2.8 m 기준)

| 재질 | 특성 | 예상 RT60 |
|------|------|-----------|
| `concrete` | 매우 반사적 | ~0.6–1.0 s |
| `brick` | 반사적 | ~0.5–0.8 s |
| `glass` | 매우 반사적 | ~0.7–1.2 s |
| `wood` | 중간 | ~0.3–0.6 s |
| `carpet` | 흡음 | ~0.15–0.3 s |
| `acoustic_tile` | 매우 흡음 | ~0.1–0.2 s |

### ISM Order 트레이드오프

| ISM Order | 이미지 소스 수 | 소요시간 | 추천 용도 |
|-----------|-------------|---------|-----------|
| 1 | 6 | 매우 빠름 | 프리뷰, 대량 배치 |
| 2 | 18 | 빠름 | 빠른 데이터셋 |
| 3 | ~38 | 보통 | **일반 데이터셋** |
| 5 | ~100 | 느림 | 고정밀 RIR |
| 8+ | ~400+ | 매우 느림 | 연구용 |

### Zoom 시나리오 방 크기 프리셋

| 프리셋 | 크기 (L×W×H) | 참여자 수 |
|--------|-------------|---------|
| `small` | 6×4×2.8 m | 2–4인 |
| `medium` | 9×5×3.0 m | 5–8인 |
| `large` | 12×6×3.5 m | 9–12인 |
| `auto` | 참여자 수로 자동 선택 | — |

### 좌표계 (Y-up Right-hand)

```
X = 0 .. L  (방 길이, 앞→뒤)
Y = 0 .. H  (높이, 바닥→천장)
Z = 0 .. W  (방 너비, 왼→오른쪽)

카메라·TV 벽 = X=0 면
테이블 중심  = (L/2, table_H/2, W/2)
사람 입 높이 = Y = 1.18 m
```

---

## 9. 테스트 실행

```bash
# 전체 테스트
python -m pytest tests/ -v

# W122 잔향 모델 단위 테스트 (30개)
python -m pytest tests/unit/test_w122_reverberation.py -v

# 커버리지 포함
python -m pytest tests/ --cov=simulator --cov-report=html
```

**핵심 스모크 테스트:**

```bash
python -c "
import sys; sys.path.insert(0, 'src')
import numpy as np
from simulator.uf.w111_room_geometry import define_room_primitive
from simulator.uf.w121_direct_path import compute_distance_and_delay
from simulator.uf.w122_reverberation import compute_image_sources
from simulator.scenarios.zoom_meeting import generate_zoom_scenario
from simulator.uf.w151_config import SceneConfigValidator

room = define_room_primitive({'type':'shoebox','dimensions':{'L':6,'W':4,'H':2.8}})
print('Room volume:', room.aabb.volume_m3, 'm3')  # 67.2

r = compute_distance_and_delay(np.zeros(3), np.array([1.,0.,0.]), 16000)
print('1m delay:', r['delay_samples'], 'samples')  # 47

imgs = compute_image_sources({'L':6,'W':4,'H':2.8}, np.array([1.,1.18,0.85]), np.array([3.,0.8,2.]), ism_order=1)
print('ISM order=1:', len(imgs), 'sources')  # 6

cfg = generate_zoom_scenario(4, 42, has_tv=True)
sc = SceneConfigValidator().validate({k:v for k,v in cfg.items() if k != '_zoom_meta'})
print('Zoom 4p:', len(sc.sources), 'sources,', len(cfg['room']['obstacles']), 'obstacles')  # 4 sources, 6 obstacles
"
```

---

## 10. 자주 묻는 질문 (FAQ)

**Q. `pip install -e .` 에서 `BackendUnavailable: Cannot import setuptools.backends.legacy` 오류가 납니다.**

A. pyproject.toml의 build-backend가 잘못 설정된 경우입니다. 현재 버전은 이미 수정되어 있습니다. 저장소를 최신으로 업데이트하거나 pyproject.toml에서 확인하세요:
```toml
[build-system]
requires = ["setuptools>=42", "wheel"]
build-backend = "setuptools.build_meta"   # 이렇게 되어 있어야 함
```

---

**Q. RT60이 너무 길게 나옵니다.**

A. 흡음 재질(`carpet`, `acoustic_tile`)을 사용하거나, 방 크기를 줄이거나, 의자 장애물(absorptive)을 더 추가하세요.

---

**Q. 음원/수음기 좌표가 방 밖으로 나갔을 때?**

A. `SceneConfigValidator`가 검증 오류를 반환합니다. 좌표는 반드시 `0 < X < L`, `0 < Y < H`, `0 < Z < W` 범위 내에 있어야 합니다.

---

**Q. Zoom 시나리오 JSON에서 `_zoom_meta` 키가 있으면 시뮬레이션이 실패합니다.**

A. `_zoom_meta`는 시나리오 메타데이터로, 시뮬레이터 검증기에 전달하기 전에 제거해야 합니다:
```python
raw.pop("_zoom_meta", None)
cfg = SceneConfigValidator().validate(raw)
```
**Tab 6 — Run from Files** 에서는 자동으로 처리됩니다.

---

**Q. WAV 파일에 아무 소리가 없습니다.**

A. V1은 화이트 노이즈를 소스 신호로 사용합니다. 음성 파일을 주입하려면 Python API에서 `source_signals` 인자를 직접 전달하세요 (v1.2 GUI 지원 예정).

---

**Q. 배치 생성이 너무 느립니다.**

A. 다음을 시도하세요:
1. ISM Order를 2로 낮추기 (속도 3배 향상)
2. Sample Rate 16000 유지 (44100은 3배 느림)
3. Tab 6 Workers 수 늘리기 (최대 8)
4. 참여자 수가 많으면 음원 수도 늘어나므로 ism_order를 더 낮추는 것이 효과적

---

**Q. `ModuleNotFoundError: No module named 'simulator'`**

A:
```bash
# 방법 1: editable install (권장)
pip install -e .

# 방법 2: 경로 수동 추가
import sys; sys.path.insert(0, 'src')
```

---

**Q. 같은 seed로 실행했는데 결과가 다릅니다.**

A. ISM과 재질 계산은 결정론적입니다. `motion` 파라미터가 있는 동적 씬에서는 타임라인 생성에 미세한 차이가 발생할 수 있습니다. 완전 재현을 위해 static 씬(motion 없음)을 사용하세요.

---

## 11. 알려진 제한사항

| 번호 | 제한사항 | 해결 예정 |
|------|----------|-----------|
| L-01 | BRIR은 합성 HRTF 사용 (CIPIC DB 미연동) | v1.2 |
| L-02 | 동적 씬 RIR은 1/r 임펄스 근사 | v1.2 |
| L-03 | Mesh 방(OBJ/STL) ISM 미지원 | v1.3 |
| L-04 | GUI에서 실제 음성 파일 입력 미지원 | v1.2 |
| L-05 | GPU 가속 없음 (CPU만) | v1.3 |
| L-06 | Zoom 씬에서 TV 반사는 obstacle로 처리 (별도 반사 모델 없음) | v1.2 |

---

## 부록: 재질별 흡음 계수 (125–4000 Hz)

| 재질 | 125 Hz | 250 Hz | 500 Hz | 1000 Hz | 2000 Hz | 4000 Hz |
|------|--------|--------|--------|---------|---------|---------|
| concrete | 0.01 | 0.02 | 0.02 | 0.03 | 0.03 | 0.04 |
| brick | 0.03 | 0.03 | 0.03 | 0.04 | 0.05 | 0.07 |
| carpet | 0.08 | 0.24 | 0.57 | 0.69 | 0.71 | 0.73 |
| glass | 0.35 | 0.25 | 0.18 | 0.12 | 0.07 | 0.04 |
| wood | 0.15 | 0.11 | 0.10 | 0.07 | 0.06 | 0.07 |
| acoustic_tile | 0.20 | 0.45 | 0.81 | 0.90 | 0.87 | 0.87 |

---

*문의사항은 [GitHub Issues](https://github.com/mrjoohk/audio_generator/issues) 또는 `W100000/` 폴더의 설계 문서를 참조하세요.*
