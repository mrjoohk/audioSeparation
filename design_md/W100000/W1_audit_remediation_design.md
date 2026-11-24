# W1 감사 개선 상세 설계 (Audit Remediation Design)

2026-11-21 · 입력: [fresh-eyes 감사 보고서](../../review_docs/261120_1716_fresh_eyes_audit.md) (F-01~F-12) · 기준 커밋 `bf28f10`

## 0. 목적과 범위

감사 보고서의 12개 발견을 **코드로 해소할 항목**과 **설계 결정으로 고정할 항목**으로 나누고, 코드 항목은 모듈·인터페이스·수용 시험 수준까지 상세화한다.

저장소에 실행 코드가 있는 것은 W1(공간 시뮬레이터)과 GUI뿐이다. W2–W4는 설계 문서만 있다. 그래서 W2–W4 쪽 발견은 첫 종단 간 검증에 꼭 필요한 **경계 계약과 재사용 가능한 검사 도구**(분할 누수 검사, 평가기 코어, 매니페스트 로더)까지만 구현한다. 나머지는 이 문서의 결정 표로 남긴다.

| 발견 | 처리 | 구현 위치 |
| --- | --- | --- |
| F-01 정상 씬 저장 중단 | 구현 | `propagation.py`, `w124_rir_rendering.py`, `scene_io.py` |
| F-02 정답 신호·시간 기준 | 구현(W1 측 계약) + 설계 | `orchestration.py`, `scene_io.py`, `datatools/loader.py` |
| F-03 실측 자료 확보 | 설계(§6.1) | — |
| F-04 누수 차단 | 구현(검사 도구) + 설계 | `datatools/splits.py` |
| F-05 평가기 정확성 | 구현(코어 지표) + 설계 | `datatools/metrics.py` |
| F-06 성공 판정 | 설계(§6.2) | — |
| F-07 GUI/API 설정 불일치 | 구현 | `config_resolver.py`, `app.py` |
| F-08 부분 실패·재개 | 구현 | `w152_batch.py`, `scene_io.py` |
| F-09 지원 범위·물리 조건 | 구현 | `capture.py`, `orchestration.py`, `config_resolver.py` |
| F-10 보정 채택 기준 | 설계(§6.3) | — |
| F-11 규모 환산 | 구현(파일럿 지표) + 설계 | `w152_batch.py` (`ExecutionSummary`) |
| F-12 요구사항·증거 연결 | 설계(§7 추적표) | 이 문서 §7 |

## 1. 코드 분석으로 추가 확인한 결함

감사 재현 결과(423 통과, 17 실패)를 같은 조건에서 다시 확인했다. 코드를 읽고 구현하면서 감사에 없던 결함 일곱 건을 더 찾았다(N-06, N-07은 구현 중 발견). 모두 F-01·F-02·F-07의 근본 원인과 연결된다.

| ID | 결함 | 근거 | 영향 |
| --- | --- | --- | --- |
| N-01 | 설정의 `sources[].position`, `receivers[].position`이 **무시된다**. `DynamicSceneOrchestrator`는 `motion` 키만 읽어 정적 궤적의 위치를 무작위로 뽑는다. | `dynamics.py:66-75`, `w131_trajectory.py:330` | 렌더 결과가 설정한 배치와 무관하다. GUI 미리보기와 실제 렌더가 다르다(F-07의 실질적 원인). |
| N-02 | 재질 맵이 씬 상태에 전달되지 않는다. `synchronize()`가 `material_map`을 받고도 `synchronize_scene_ticks`에 넘기지 않는다. | `dynamics.py:102-132` | 재질 선택이 RIR에 반영되지 않는다. Sabine 추정은 예외 경로로 0.5 s 고정값이 된다. |
| N-03 | 모든 음원·수음기 쌍과 모든 씬이 같은 후기 잔향 시드(42)를 쓴다. | `propagation.py:100` | 쌍별 참조가 독립적이지 않다. 데이터셋 전체에 같은 잔향 꼬리 패턴이 반복된다. |
| N-04 | 정적 궤적 위치를 0.5 m 벽 여유로 **조용히 이동**시킨다. Zoom의 TV 스피커(벽에서 0.1 m)가 0.5 m로 옮겨진다. | `w131_trajectory.py:384`, `w132_receiver_trajectory.py:362` | 설정과 렌더 기하가 어긋나지만 경고나 기록이 없다. |
| N-06 | 궤적 생성에 설정 ID를 넘기지 않아 모든 음원이 `source_0`, 모든 수음기가 `receiver_0`가 된다. | `dynamics.py:70-90`, `w131_trajectory.py:282` | 기존 `render_scene`은 ID가 맞는 건조 신호를 찾지 못해 음원을 모두 건너뛰었다. F-01이 고쳐져도 출력 WAV는 장치 잡음뿐이었다. |
| N-07 | ISM 홀수 차수 이미지 좌표가 `n·L − x`로, 원점 중심 방을 가정한다. 방은 `[0, L]`이다. | `w122_reverberation.py:_reflect_coord` | 1차 반사가 직접파보다 먼저 도달하는 비물리적 RIR. `(n+1)·L − x`로 수정하고 벽 충돌 횟수 규칙과 일치시켰다. |
| N-05 | 씬 길이 기본값이 경로마다 다르다(렌더 5 s, 궤적 10 s). DOA는 항상 `None`이며 GUI 요약이 `None`에 `:.1f`를 적용해 예외가 난다. | `orchestration.py:222`, `dynamics.py:62`, `app.py:240` | 시간축 계약이 불명확하고 GUI 단일 씬 실행이 성공해도 요약 단계에서 실패한다. |

## 2. 렌더 프로필과 지원 범위 (F-09, N-04, N-05)

첫 검증 범위로 **`static_v1`** 프로필 하나를 정의한다. 지원하지 않는 입력은 렌더 전에 거부한다. 근사 처리를 할 때는 결과 메타데이터에 남긴다.

| 항목 | `static_v1` 지원 | 지원 밖 입력의 처리 |
| --- | --- | --- |
| 방 | `shoebox` | `corridor`/`hall`은 경고 후 직육면체 ISM 근사, `approximations`에 기록 |
| 음원·수음기 운동 | `static` (또는 `motion` 없음) | 오류 `UnsupportedProfileError`. `render.allow_static_approximation: true`이면 첫 틱으로 렌더하고 `approximations`에 기록 |
| 수음기 지향성 | `omni` | 다른 `pattern`은 오류. 지향성은 음원별 직접파에 걸어야 하므로 혼합 후 채널 단위 적용은 물리적으로 틀리다 |
| 바이노럴 | 미지원 | 오류 |
| 배열 오차 | `impairments.array_errors` (§4.3) | — |
| 샘플레이트 | 8/16/22.05/44.1/48 kHz | 검증 오류 |
| 씬 길이 | `motion.duration_s` 하나, 기본 **5.0 s** | 렌더·궤적·사전 검사가 같은 상수 `DEFAULT_DURATION_S`를 쓴다 |

**위치 규칙(N-01, N-04).** 정적 엔터티의 `position`은 `motion.position`보다 우선하지 않고, `motion`에 위치가 없을 때 채운다. 명시 위치는 벽 여유로 이동시키지 않는다. 방 밖 좌표는 설정 검증에서 오류로 처리한다. 좌표계는 Y-up 오른손계, `[x, y, z]`이며 `x∈[0,L]`, `y∈[0,H]`, `z∈[0,W]`이다.

**대역 처리 한계(F-09).** 초기 반사 계수와 Sabine 추정은 500 Hz 대역 값을 쓴다. `static_v1`의 검증된 물리량은 직접파 지연·감쇠, 이미지 소스 지연, 대역 무관 RT60·DRR로 한정하고 매니페스트 `render.validated_quantities`에 적는다. 대역별 잔향은 후속 프로필의 범위다.

## 3. W2→W1→W3 데이터 계약 (F-02)

### 3.1 입력

| 필드 | 형식 | 규칙 |
| --- | --- | --- |
| `sources[i].source_id` | `[A-Za-z0-9_.-]{1,64}` | 씬 안에서 고유해야 한다. 중복은 검증 오류 |
| `sources[i].signal_path` | WAV 경로(선택) | 다채널이면 평균해 모노로 만든다. 샘플레이트가 다르면 `resample_poly`로 변환하고 기록한다. 없으면 시드 기반 백색잡음(−40 dBFS RMS) |
| `sources[i].onset_s` | float ≥ 0 (기본 0) | 건조 신호를 씬 타임라인에 놓는 시각 |
| `sources[i].level_dbfs` | float(선택) | 활성 구간 RMS를 이 값으로 맞춘다 |
| `receivers[i]` 장치 파라미터 | `gain_db`, `noise_floor_dbfs`, `clip_threshold_dbfs`, `sensitivity_db` | **채널별**로 적용한다(§4.2) |
| `reference_receiver` | receiver_id(선택) | 기본은 `receivers[0]` |

`signal_path` 파일의 SHA-256은 작업 지문(§5.1)에 들어간다.

### 3.2 시간축

* 공통 샘플 인덱스 0은 **씬 시작 = 음원 방사 기준 시각**이다. 모든 출력 파형은 같은 인덱스를 쓴다.
* 건조 타임라인 길이 `N_dry = round(duration_s · fs)`. 음원 s는 `[o_s, o_s + n_s)`에 놓인다. 신호가 타임라인을 넘으면 잘라내고 `truncated: true`를 기록한다.
* 렌더 길이 `T = N_dry + L_max − 1` (`L_max`는 씬의 최대 RIR 길이). 모든 성분을 0으로 채워 `T`에 맞춘다. 잔향 꼬리는 자르지 않는다.
* 음원 s의 수음기 c 도달 구간은 `[o_s + d_sc, o_s + n_s + d_sc)`이다. `d_sc`는 직접파 지연(샘플)이다.
* 라벨 정렬 허용치는 **1 ms 미만**이다. 16 kHz에서 15샘플 오차는 통과, 16샘플은 실패한다(`check_label_alignment`).
* 배열 시계 오차는 채널 c의 혼합음과 그 채널의 모든 참조에 같은 정수 시프트로 적용하고 `time_transforms`에 기록한다. 시프트 뒤에도 참조와 혼합음은 같은 시간축에 있다.

### 3.3 출력과 정답 정의

| 성분 | 모양 | 정의 | 파일 |
| --- | --- | --- | --- |
| 분리 정답(참조) | `[S, C, T]` | 마이크 위치에서 렌더한 **기기 열화 전** 음원별 수음 파형 `y_sc = h_sc * x_s` | `reference__{src}__{rec}.wav` |
| 열화 전 혼합음 | `[C, T]` | `Σ_s y_sc` (float64 누적) | 저장하지 않고 QC에서 검사 |
| 혼합음(관측) | `[C, T]` | 열화 전 혼합음에 수음 체인(감도→자체잡음→이득→클리핑→코덱)을 적용 | `mixture__{rec}.wav` |
| 장치 잡음 성분 | `[C, T]` | 자체잡음 단계에서 더한 잡음(이득 적용 후) | `noise__{rec}.wav` |
| 건조 신호 | `[S, N_dry]` | 타임라인에 배치한 건조 신호 | `dry__{src}.wav` |
| RIR | `[S, C, L]` | 쌍별 RIR | `rir__{src}__{rec}.wav` |

구분자로 이중 밑줄을 쓴다. ID에는 밑줄 하나만 허용되므로 파일명을 ID로 되돌릴 때 모호하지 않다.

**검사 규칙.** 열화 전에는 `max|Σ_s y_sc − mix_pre_c| ≤ 1e-5 · max(1, peak)`로 **성분 합**을 검사한다. 열화 후에는 비선형 단계(클리핑, 코덱, 패킷 손실)가 있으므로 합 대신 **정렬·유효 구간·유한성**을 검사한다. 비선형 단계가 실제로 샘플을 바꿨는지는 `device.nonlinear_applied`와 `clipped_samples`로 기록한다.

**SNR·중첩률 정의.** 기준 채널에서 계산한다.
* `snr_db[s] = 10·log10( P(y_s,ref) / P(noise_ref) )`, 두 전력 모두 음원 s의 도달 구간에서 계산한다.
* `overlap_ratio = |{t : 활성 음원 ≥ 2}| / |{t : 활성 음원 ≥ 1}|`. 활성은 도달 구간 기준이다. 분모가 0이면 0으로 정의한다.
* 활성 구간은 배치 구간이다. 건조 신호 내부의 무음은 활성으로 센다. VAD 기반 정의는 W2 실음성 도입 때 정한다.

**DOA.** 수음기 좌표계(방향 쿼터니언 적용 후)에서 `az = atan2(dx, dz)`, `el = asin(dy/‖d‖)`이다. 쌍별 값을 `geometry.pairs`에 기록하고, 요약 DOA는 첫 음원과 기준 수음기의 값이다.

### 3.4 씬 매니페스트 v2

`<output_root>/<scene_id>/scene_manifest.json`. 경로는 모두 **출력 루트 기준 상대 경로**다. 로더는 원래 생성 위치에 의존하지 않는다. v1 필드(`audio_files`, `rir_files`, `acoustic_summary`)는 하위 호환을 위해 유지한다.

```text
schema_version "2.0.0", scene_id, fingerprint, renderer_version, created_at
render:   profile, fs, n_samples(T), n_dry, duration_s, reference_receiver,
          approximations[], validated_quantities[], tail_policy
sources:  [{source_id, onset_sample, n_samples, truncated, signal{kind, path?, sha256?, resampled_from?}}]
receivers:[{receiver_id, nominal_position, effective_position, clock_shift_samples, device{...}}]
geometry: pairs[{source_id, receiver_id, distance_m, direct_delay_samples, doa_az_deg, doa_el_deg,
                 arrival_start, arrival_end}]
labels:   overlap_ratio, snr_db{src}, activity{src: [start,end] at reference}
files:    [{path, role(mixture|reference|noise|dry|rir|params|summary), source_id?, receiver_id?,
            channels, n_samples, encoding "float32", sha256}]
qc:       {passed, checks{name: bool}, flags[], details{}}
device:   {snr_per_channel_db, clipped_samples[], nonlinear_applied, impairment{...}}
```

## 4. 모듈 상세 설계

### 4.1 RIR 생성 (F-01, N-03)

* `AcousticPropagationEngine.generate_rir()`는 지원되지 않는 `src_pos` 인자를 넘기지 않는다.
* `generate_static_rir()`와 `generate_static_rir_with_mic()`를 하나의 구현으로 합친다. `mic_pos=None`이면 기존 원점 기준 동작을 유지하되 경고한다.
* **후기 잔향 크기 결정.** 꼬리 전체 RMS를 목표값에 맞추던 방식 때문에 RT60이 짧고 혼합 시각이 늦을 때 꼬리 시작점이 직접파보다 커졌다(감사의 "직접파 피크 오차"). 꼬리 길이가 0이면 평균이 NaN이 됐다. 새 규칙에서는 꼬리 포락선이 t=0에서 `A0 = 0.1·직접파 진폭`으로 시작해 `exp(−6.9 t / RT60)`로 감쇠했다고 보고, 혼합 시각에서 연속이 되도록 `A0 · exp(−6.9 t_mix / RT60)`로 맞춘다. 꼬리 길이 0과 0 RMS는 건너뛴다.
* 후기 잔향 시드는 `crc32(f"{scene_seed}:{src}:{rec}")`로 쌍마다 결정적으로 다르게 만든다.
* RIR은 유한성을 검사한다. NaN/Inf가 있으면 `ValueError`를 낸다.

### 4.2 수음 체인 (F-09)

* 채널별 파라미터: `CaptureDeviceChain`은 `receivers[c]`에서 `gain_db`, `noise_floor_dbfs`, `clip_threshold_dbfs`, `sensitivity_db`를 읽는다(기존 구현은 `receivers[0]`만 읽음).
* 자체잡음 성분을 체인 출력과 함께 돌려준다(`return_components=True`). 잡음 성분에도 해당 채널 이득을 적용해 관측 혼합음과 같은 척도로 맞춘다.
* dBFS 규약은 AES17이다. 풀스케일 사인파가 0 dBFS이므로 잡음 바닥 `L` dBFS의 RMS는 `10^(L/20)/√2`이다. −20 dBFS 사인과 −60 dBFS 잡음의 SNR은 40 dB다.
* 패킷 손실 PER은 요구사항대로 [0, 0.2]이다. 범위를 벗어나면 `ValueError`를 낸다. 스트레스 조건은 `allow_stress=True`일 때만 [0, 1]을 허용한다.

### 4.3 배열 오차 (F-09)

`impairments.array_errors = {position_sigma_m: float ≥ 0, max_clock_skew_samples: int ≥ 0}`.
* 위치 오차는 **전파 계산 전에** 수음기 좌표에 더한다. 시드는 `array` 서브시스템 시드에서 수음기별로 파생한다. 명목·유효 좌표를 모두 매니페스트에 기록한다.
* 시계 오차는 채널별 정수 시프트 `k_c ∈ [−K, K]`로 혼합음과 그 채널의 참조에 함께 적용한다(§3.2).
* TDOA 검증은 두 시험으로 나눈다. (a) 직접파 지연차가 기하 계산과 ±1 샘플 안에서 일치한다. (b) 방향 복원은 배열 축과 동일 평면에 있는 관측 조건에서만 시험한다. 2마이크 한 쌍으로 임의 3D 방향을 유일하게 구할 수 없음을 요구사항 주석으로 남긴다.

### 4.4 무결성, QC, 원자적 확정 (F-01, F-08, F-11)

`simulate_scene()` 흐름:

1. 설정 해석(§4.6)과 프로필 검사
2. `<root>/.staging/<scene_id>-<uuid>/`에 모든 파일을 쓴다.
3. QC 검사: 유한성, 성분 합, 파일 왕복(다시 읽어 dtype·모양·값 일치), 매니페스트 파일 목록과 실제 파일 일치, 쌍별 참조 고유성(서로 다른 쌍의 참조가 같지 않음), 라벨 정렬
4. 통과하면 기존 `<root>/<scene_id>`를 `.trash`로 옮기고 스테이징 디렉터리를 최종 이름으로 바꾼 뒤 휴지통을 지운다.
5. 실패하면 스테이징 디렉터리를 `<root>/_quarantine/<scene_id>/`로 옮기고 `qc_failure.json`에 이유를 쓴 뒤 `SceneQCError`를 낸다.

WAV는 `scipy.io.wavfile.write`로 **IEEE float32**(`WAVE_FORMAT_IEEE_FLOAT`)를 쓴다. 기존 `wave` 모듈 경로는 float 바이트를 PCM int32로 표시해 값이 바뀌었다.

**QC 처분.** 헤드룸 초과(피크 > 0 dBFS 전)는 `flag`, 실제 클리핑은 `flag`와 `clipped_samples` 기록이다. `qc.fail_on_clip: true`이면 실패로 처리한다. 의도한 스트레스 조건(`allow_stress`)은 `flag`만 남긴다. 위 3단계의 무결성 검사 실패는 언제나 `fail`이다.

### 4.5 작업 식별과 재개 (F-08, F-11)

* **작업 지문** `fingerprint = sha256(canonical_json({resolved_config − {scene_id, output_dir, _*}, renderer_version, asset_sha256}))`. 표시 ID와 출력 위치가 바뀌어도 렌더 조건이 같으면 지문이 같다.
* **체크포인트 v2**: `{"schema": 2, "jobs": {scene_id: {fingerprint, status, reason, updated_at}}}`. v1(완료 ID 목록)은 읽되 지문이 없으므로 산출물 검증을 통과해야만 완료로 인정한다.
* 작업을 건너뛰는 조건은 세 가지를 모두 만족할 때다. (1) 체크포인트 상태가 `completed`이고 지문이 같다. (2) 매니페스트가 존재하고 지문이 같다. (3) 모든 파일이 존재하고 체크섬이 같다(`verify="checksum"`, 대량 재개 시 `"exists"` 선택 가능).
* 같은 배치에서 지문이 같은 다른 scene_id는 `duplicate_groups`로 보고한다.
* `ExecutionSummary`에 `n_skipped`, `failure_reasons`, `audio_seconds_completed`, `bytes_written`, `qc_passed_audio_hours_per_hour`를 추가한다. 파일럿 실행에서 이 값으로 F-11의 처리량·저장량 환산을 측정한다.
* `worker_count == 1`이면 프로세스 풀 없이 순차 실행한다(재현·디버깅용).

### 4.6 설정 해석기 — GUI/API 공통 (F-07)

새 모듈 `simulator/config_resolver.py`:

| 함수 | 역할 |
| --- | --- |
| `load_raw_config(path)` | JSON/YAML 공통 로더. GUI 가져오기도 이 함수를 쓴다 |
| `resolve_config(raw)` | 기본값 적용, `position` 정규화(리스트/`{x,y,z}`), 정적 운동에 위치 주입, 해석된 dict 반환 |
| `apply_editor_overrides(base, edits, max_sources, max_receivers)` | 편집기가 다루는 필드만 바꾼다. ID와 미편집 필드(장애물, 운동, 장치, `_zoom_meta`)를 보존한다. 편집기 용량을 넘는 음원·수음기는 그대로 둔다 |
| `scene_signature(raw)` | 지문(§4.5)과 같은 규칙의 서명. 미리보기·실행·왕복 비교에 쓴다 |
| `preflight(raw)` | 해석된 설정, 오류, 경고, 지원 밖 항목, 근사, 예상 작업량(쌍 수, T, 저장 바이트) |

GUI 변경:
* `gr.State`에 가져온 원본 설정을 저장한다. 내보내기와 실행은 `apply_editor_overrides(base, edits)`의 결과를 쓴다.
* 가져오기 상태 메시지에 "편집기 표시 N개 / 보존 M개", 장애물 수, 서명을 표시한다.
* 파일 실행 탭은 워커 수를 실제로 쓰고(`run_config_files`), 완료·실패·건너뜀 건수를 따로 보고한다. 실패가 있으면 완료 표시(✅)를 쓰지 않는다.
* 요약 표는 `None` 값을 `—`로 표시한다.

### 4.7 데이터 도구 (F-02, F-04, F-05)

새 패키지 `src/datatools/`:

* `loader.load_scene(manifest_path)` → `SceneBundle(mixture[C,T], references[S,C,T], noise[C,T], fs, source_ids, receiver_ids, manifest)`. 체크섬, 모양, 샘플레이트, 지문(선택적 기대값)을 검증한다. `check_label_alignment(reference, dry, expected_onset, fs, tol_ms=1.0)`도 이 모듈에 둔다.
* `splits.check_split_leakage(items, group_keys)` → 금지 교집합 목록. `items`는 `{id, split, keys{speaker, recording, session, room, noise, device}}`이다. 모든 분할 쌍(train–val, train–test, val–test, dev–blind)을 검사한다. `assign_groups()`는 연결된 원본 자산을 하나로 묶어 **합성 전에** 분할한다(union-find). `verify_benchmark_manifest(path, expected_sha256)`는 선언된 기대 해시와 비교한다. 서버 간 해시 일치만으로는 모두가 같은 잘못된 버전을 읽는 경우를 놓친다.
* `metrics`: `si_sdr`, `si_sdr_improvement`(혼합음 기준 채널 대비), `permutation_match`(최적 순열, 누락·추가 화자 처리), `normalize_text`, `wer`(다중 스트림은 시각 순으로 결합). 정답을 미리 계산한 작은 예제로 도구 정확성을 시험한다(§7).

## 5. 오류 모델

| 예외 | 발생 조건 | 배치 처리 |
| --- | --- | --- |
| `ValidationError` | 스키마·ID·좌표·범위 오류 | `failed`, reason=`validation` |
| `UnsupportedProfileError` | §2의 지원 밖 입력 | `failed`, reason=`unsupported_profile` |
| `SceneQCError` | §4.4 무결성 검사 실패 | `failed`, reason=`qc:<check>`, 산출물 격리 |
| 기타 | 렌더 예외 | `failed`, reason=`error:<type>` |

## 6. 설계 결정 (코드 밖)

### 6.1 실측 자료 등록 (F-03)

세션 단위 등록부 `real_sessions.csv`의 필수 열: `session_id, source(출처), license_scope, consent_verified, room_id, device_id, mic_layout, sync_method, device_dsp(on/off/unknown), has_ref_wave, has_transcript, has_speaker_timeline, has_position, annotation_qc_sample, split`.

| 태스크 | 필요한 정답 | 최소 수량(2026-11-23 승인) | 정답이 없을 때 |
| --- | --- | --- | --- |
| 분리(SI-SDRi) | 근접 마이크 참조 파형 | 세션 20개, 검수 10% | 비지도/혼합 일관성 손실만 허용, SI-SDRi 보고 제외 |
| ASR(WER) | 전사 | 2시간 | 해당 지표 분모에서 제외하고 유효 분모 표시 |
| 화자 분할(DER) | 화자 타임라인 | 2시간 | 동일 |
| 위치(각도 오차) | 위치 정답과 좌표계 | 출시 범위일 때만 | 지표 미보고 |

### 6.2 성공 판정 (F-06)

같은 세션에서 **원음 / 고정 기준 분리 모델 / 후보 모델**을 비교한다.

| 지표 | 비교 기준 | 합격 조건(2026-11-23 승인) | 경계·동률 |
| --- | --- | --- | --- |
| WER | 고정 기준 모델 | 절대 −3.0 %p 이상 개선 (REQ-305) | 정확히 −3.0 %p는 합격. 기준 WER 0이면 후보도 0이어야 합격 |
| WER | 원음 | 상대 −15 % 이상 (REQ-402) | 기준 WER 0이면 상대값 대신 절대 +0.5 %p 이하 악화로 판정 |

2026-11-24 개정(제품 책임자 승인): 위 두 WER 행(REQ-305·REQ-402)의 WER은 **cpWER**(화자별 연결 최소 순열 WER, §17)이다. 임계값, 20세션, CI 규칙은 그대로다. blind2·blind3에는 소급하지 않는다. 회귀 행(REQ-405)은 개정 범위 밖이라 시간순 결합 WER을 그대로 쓴다.

| 주요 조건별 회귀 | 고정 기준 모델 | 어떤 조건도 WER 절대 +0.5 %p 이상 악화 금지 (REQ-405 "1% 미만"을 %p로 고정) | 0.5 %p 이상은 실패 (REQ-405 수용 사례 "0.5% 악화 → Fail"과 일치하도록 경계 포함, 2026-11-21 정정) |
| 불확실성 | 세션 쌍 비교 | 세션별 차이의 부트스트랩 95% CI 상한 < 0 | 표본 < 20 세션이면 판정 보류 |

DER·SDR은 진단 지표로 보고하고 합격 조건에는 넣지 않는다. 위치 추정을 출시 범위에 넣을 때 별도 요구사항(각도 오차, 거리 오차, 추적 단절률, 좌표계)을 정의한다.

### 6.3 보정·적응 채택 (F-10)

* RT60 분포 일치와 판별기 BCE는 **진단**이다. BCE 0.69는 상수 0.5 출력으로도 달성되므로 합격 조건으로 쓰지 않는다.
* 채택 조건은 적합에 쓰지 않은 dev 세션에서의 태스크 이득(§6.2)과 회귀 금지다.
* W3 보정 결과는 W2 생성 매니페스트의 `calibration_profile{id, data_version, fit_sessions[], parameter_ranges}`로 전달한다. W2는 이 필드가 없는 분포를 승인된 보정으로 취급하지 않는다.
* 요인 제거(REQ-404)는 데이터·예산·시드를 고정하고, 효과가 큰 두 요인의 조합 실험을 추가한다.

### 6.4 규모 환산 (F-11)

16 kHz float32 기준 1 오디오 시간 = 230.4 MB/채널. 10만 시간 × (4채널 혼합 + 2화자 × 4채널 참조 = 12채널)은 276.48 TB다. 파일럿에서 `ExecutionSummary.qc_passed_audio_hours_per_hour`와 `bytes_written`을 측정한 뒤 저장 프로필(예: 참조는 기준 채널만, FLAC/int16)과 목표 규모를 다시 정한다.

## 7. 수용 시험 추적표 (F-12)

| 요구 | 시험 | 파일 |
| --- | --- | --- |
| F-01 1음원·1수음기와 2음원·2수음기 씬 저장 | `test_e2e_1x1_scene`, `test_e2e_2x2_scene` | `tests/integration/test_e2e_contract.py` |
| F-01 직접파 피크, 유한 RIR | `test_rir_direct_peak`, `test_rir_drr_anechoic`, `test_rir_finite_short_rt60` | `tests/unit/test_w124_rir_rendering.py` |
| F-01 WAV 왕복 | `test_wav_float32_roundtrip` | `tests/unit/test_scene_io.py` |
| F-02 성분 합·쌍별 고유 참조 | `test_e2e_2x2_scene` | `test_e2e_contract.py` |
| F-02 1 ms 정렬 경계(15/16샘플) | `test_label_alignment_boundary` | `tests/unit/test_datatools.py` |
| F-02 중복 ID 거부 | `test_duplicate_source_id_rejected` | `tests/unit/test_w151_config.py` |
| F-02 설정 위치 반영 | `test_config_positions_are_rendered` | `test_e2e_contract.py` |
| F-04 누수 검사 | `test_split_leakage_*`, `test_session_registered_twice_fails` | `test_datatools.py` |
| F-05 지표 정확성 | `test_si_sdr_golden`, `test_permutation_*`, `test_wer_golden` | `test_datatools.py` |
| F-07 Zoom 왕복 서명 유지 | `test_zoom_roundtrip_signature` | `tests/unit/test_config_resolver.py` |
| F-08 재개 | `test_resume_skips_verified`, `test_resume_reruns_on_seed_change`, `test_resume_reruns_on_missing_output`, `test_resume_ignores_legacy_checkpoint_without_output` | `tests/integration/test_batch_resume.py` |
| F-08 격리 | `test_qc_failure_quarantines` | `test_batch_resume.py` |
| F-09 채널별 이득 | `test_per_channel_gain_applied` | `tests/integration/test_capture_chain.py` |
| F-09 배열 오차 적용 | `test_array_errors_change_geometry` | `test_e2e_contract.py` |
| F-09 지원 밖 프로필 거부 | `test_moving_source_rejected` | `test_e2e_contract.py` |

## 8. 기존 시험 수정 근거

| 시험 | 변경 | 근거 |
| --- | --- | --- |
| `test_packet_loss_all_dropped` | `allow_stress=True` 추가 | W1 요구사항은 PER 0–20%이고 같은 파일의 `test_packet_loss_invalid_per`가 0.5에서 `ValueError`를 요구한다. 두 시험이 모순이므로 요구사항을 기준으로 스트레스 모드를 분리했다. |
| `test_rir_direct_peak_at_correct_delay` (통합) | "최대 피크 = 직접파"를 "첫 도달 = 직접파, 그 앞에 에너지 없음"으로 변경 | 시험 배치는 수음기를 벽면(z = W = 4.0) 위에 두고 대칭이다. N-07을 고치면 1차 이미지 4개가 같은 시각에 도달하고, 그 합이 직접파보다 크다. 물리적으로 맞는 결과이므로 시험이 확인해야 할 성질은 인과성이다. |

| `test_len_prepopulated` (재질 DB) | 기본 재질 수 7 → 8 | REQ-W04의 "무반향(α = 1) DRR > 40 dB" 시험과 REQ-W03 TDOA 시험을 위해 `anechoic` 재질을 추가했다. 시험은 기본 재질 표의 크기를 확인하는 불변식이다. |

나머지 기존 실패 시험은 시험을 바꾸지 않고 코드를 고쳤다.
* 웨이포인트 종점: 구간 인덱스를 자른 뒤 구간 내 비율을 계산한다.
* 장애물 높이: 기존 시험이 6면 모두 0.3 m 여유를 요구하므로 규칙은 유지한다. 수직 여유를 둘 수 없는 키 큰 물체만 바닥에 세우고 경고한다.
* SNR: dBFS를 AES17(풀스케일 사인 = 0 dBFS)로 정의했다.
* 정적 RIR: §4.1의 잔향 크기 규칙.

## 10. 구현 현황 (2026-11-21)

| 항목 | 상태 | 위치 |
| --- | --- | --- |
| §2 `static_v1` 프로필 검사 | 구현 | `config_resolver.check_profile`, `scene_pipeline.simulate_scene` |
| §3 데이터 계약, 매니페스트 v2 | 구현 | `scene_pipeline.py`, `datatools/loader.py` |
| §4.1 RIR 수정, N-03, N-07 | 구현 | `w124_rir_rendering.py`, `propagation.py`, `w122_reverberation.py` |
| §4.2 채널별 장치, 잡음 성분, AES17, PER | 구현 | `capture.py`, `w143_noise_gain.py`, `w144_codec.py` |
| §4.3 배열 오차 | 구현 (TDOA 방향 복원 시험은 미구현) | `scene_pipeline.apply_array_errors` |
| §4.4 QC, 원자적 확정, 격리 | 구현 | `scene_io.py` |
| §4.5 지문, 체크포인트 v2, 파일럿 지표 | 구현 | `w152_batch.py`, `types.ExecutionSummary` |
| §4.6 설정 해석기, GUI 연결 | 구현 (실제 브라우저 클릭 확인은 남음) | `config_resolver.py`, `runner.py`, `app.py` |
| §4.7 데이터 도구 | 구현 | `src/datatools/` |
| §6 설계 결정 | 2026-11-23 제품 책임자 승인(§6.1 정답 결측 규칙, §6.2 판정 규칙) | 이 문서, `configs/decision_rules.yaml` |

시험: 기존 440개(감사 시점 17개 실패)와 신규 66개, 총 506개 통과 (Python 3.14, numpy 2.5, scipy 1.18).

남은 관찰: Zoom 시나리오 생성기는 의자끼리, 의자와 벽이 겹치는 배치를 만든다(씬 매니페스트 `plausibility.warnings`에 기록됨). 감사 범위 밖이므로 별도 과제로 남긴다.

## 9. 남는 위험과 확인 필요

* §6의 임계값과 정답 결측 규칙은 2026-11-23 제품 책임자가 승인했다. 실측 자료의 접근 범위는 코퍼스 공개 조건(AMI CC BY 4.0)으로 확인했다.
* `static_v1` 밖의 이동 렌더(`w134`)는 정적 입력 동등성 시험이 생길 때까지 정상 경로에 연결하지 않는다.
* GUI는 이 환경에서 Gradio를 불러올 수 없어(Windows 애플리케이션 제어 정책이 `pydantic_core` DLL을 차단) 콜백 로직을 순수 모듈로 옮겨 시험한다. 실제 UI 클릭 확인은 남아 있다.


## 11. 2단계 추가 결정 (2026-11-21)

* **분수 지연(`render.fractional_delay`)**: REQ-W03은 "지연을 1/Fs로 양자화"하면서 2마이크 TDOA 각도 오차 < 1°를 요구한다. 0.2 m 쌍은 16 kHz에서 TDOA 범위가 ±9.3 샘플이라 정수 지연 한 칸이 수 도의 각도다. 두 조건은 정수 지연에서 함께 만족할 수 없다. 기본값은 정수 지연(요구사항 문구)으로 두고, 배열·TDOA 데이터는 Hann 창 sinc(반폭 16탭) 분수 지연을 켠다. 이때 QC의 도달 시각 허용치는 커널 반폭만큼 넓힌다.
* **후기 잔향 크기**: 면별 500 Hz 반사계수 평균 `mean(sqrt(1-α))`을 곱한다. 완전 흡음(α = 1)에서는 후기 잔향이 0이 되어 REQ-W04의 무반향 DRR > 40 dB를 만족한다.
* **저장 프로필(`render.storage_profile`)**: `full`(혼합·참조·잡음·건조·RIR)과 `training`(혼합·참조). 파일럿에서 10 s·2음원·4마이크 씬은 각각 16.1 MB, 10.0 MB였다.
* **처리량**: ISM 열거와 이미지 배치를 벡터화하고 후기 잔향을 float32로 생성했다. 8 워커 정상 상태 1,578 RIR/s(REQ-W04 ≥ 1,000), 시간당 약 13,000 씬(REQ-W10 ≥ 1,000). 근거: `reports/perf/`.

## 12. 5–6단계 추가 결정 (2026-11-21)

* **후기 잔향 시작점**: 혼합 시각을 직접음 도달 시각부터 잰다. 흡음이 큰 방의 먼 음원에서 잔향 꼬리가 직접음보다 먼저 시작하던 결함을 QC(`label_alignment`)가 잡았다.
* **배열 데이터와 분수 지연**: 5 cm 배열에서 정수 지연의 방위 오차는 8–12°, 분수 지연은 2° 이하였다. W2 계획기는 다채널 배열이면 `fractional_delay`를 자동으로 켠다.
* **`dynamic_v1` 프로필(REQ-W06)**: 틱마다 Hann 창으로 건조 신호를 나누고(창의 합 = 1), 음원·수음기가 5 cm 넘게 움직였을 때만 RIR을 다시 계산한다. 정적 장면은 단일 컨볼루션과 같다(−80 dB 미만 오차). 경계 클릭이 없다(500 Hz 톤, 1 m/s에서 4 kHz 이상 에너지 < −60 dB). 라벨은 틱별 지연 추적으로 도달 시각에 사상하고, `labels.doa_trace`에 틱별 방위·지연을 남긴다. 도플러는 모델링하지 않는다. 독립 렌더러가 없으므로 성분 합 QC는 `not_applicable`로 기록한다.
* **경로별 수음기 모델**: 지향성(1차 패턴)과 바이노럴(합성 구형 머리 HRTF)을 직접파와 각 이미지 소스에 그 경로의 도달 방향으로 적용한다. 후기 잔향에는 확산장 이득을 곱하고, 두 귀의 꼬리는 서로 다른 시드로 비상관화한다. 바이노럴 수음기는 `<id>.L`, `<id>.R` 두 채널로 확장된다. 좌표 규약은 전방 +z, 오른쪽 귀 −x다.
* **합성 HRTF ITD**: Woodworth 식을 원래 방위각이 아니라 측방각 `asin(sin az · cos el)`에 적용하도록 고쳤다. 뒤쪽 음원에서 ITD가 물리적 최대값을 넘던 결함이다.
* **대역별 잔향(`render.band_reverb`)**: 옥타브 대역(125 Hz–4 kHz)별로 이미지 이득과 Sabine RT60을 계산한다. 반사와 꼬리는 인과적 대역 필터로 걸러 합치고, 직접파는 광대역으로 유지한다.
* **이벤트 주입**: 짧은 과도음(노크, 키보드 클릭)을 `interference` 역할 음원으로 넣는다. 이벤트 자산도 분할 키(`event`)로 누수를 검사한다.

## 13. 7–8단계 결정 (2026-11-21)

**W3 도메인 격차(7단계).** 실측 자료가 없으므로 "실측" 영역은 **대리 영역**으로 시험한다. 대리 영역은 다른 방, 보정된 RT60, 대역별 잔향, 4 kHz 대역 제한 기기, 채널 감도 불일치, 학습에 없던 배열 3종으로 구성한다. 결과는 실측 성능이 아니다.

* REQ-301 `training/curriculum.py`: 도메인 비율은 배치마다 누적 보정해 목표를 유지한다(1만 스텝에서 ±5 % 이내). 커리큘럼은 난이도 단계 가중치를 선형으로 옮긴다. `Prefetcher`는 소비자 대기 비율을 잰다.
* REQ-302 `training/calibration.py`: 블라인드 RT60은 자유 감쇠의 T20 중앙값으로 구하고, 잡음이 크면 T15로 낮춘다. 보정 프로필은 W2 계획기의 `ScenarioPrior.calibration`으로 전달된다. 계획기는 장면마다 목표 RT60을 뽑고, 역 Sabine으로 균일 흡음률을 정한다. 이를 위해 재질 설정이 `{"alpha": [...]}` 형태를 받게 했다. 분포 일치는 KL로 진단한다.
* REQ-303 `training/augment.py`: 이득, 기울기 EQ, 대역 제한을 혼합음과 참조에 똑같이 거는 선형 증강이다. 채널 간 위상차는 보존한다. 특징 정규화(대역별 중앙값 기준)는 선택이다.
* REQ-304 `training/adaptation.py`: 라벨 없는 대상 영역 특징으로 CORAL을 정렬한다. 영역 판별기 BCE는 진단으로만 쓰고, 채택은 dev 쌍 비교 CI의 하한이 0보다 클 때로 정한다(§6.3).

**W4 판정(8단계).**

* REQ-403 `evaluation/benchmark.py`: 벤치마크 명세는 릴리스 매니페스트의 해시를 **선언값**으로 고정한다. 샤드는 캐시로 풀어 원 렌더 폴더에 의존하지 않는다. 장면 순서는 scene_id 정렬로 결정적이고, 데이터 텐서 해시를 비교한다. 서버 간 일치만으로는 모두가 같은 잘못된 버전을 읽는 경우를 놓치므로 선언 해시를 쓴다.
* REQ-404 `evaluation/ablation.py`: 요인별 영향(%), 2요인 상호작용, 지표 간 변화량 상관을 Markdown과 PDF로 낸다.
* REQ-405 `evaluation/gate.py`, `scripts/release_gate.py`: `configs/decision_rules.yaml`을 읽는다. 회귀 경계는 **0.5 %p 이상이면 실패**로 정정했다(REQ-405 수용 사례와 일치). 규칙 상태가 `proposed`이면 판정은 권고로 표시된다(2026-11-23 `approved`로 바뀌어 지금은 판정이 출시를 막는다). 종료 코드는 통과 0, 실패 1, 판정 보류 2다.
* REQ-406(제안, W414): 위치·추적 지표로 방위 오차, 재현율·정밀도, ID 전환, 단절을 쓴다. 이동 음원 장면은 `labels.doa_trace`를 정답으로 쓴다.
* F-12 `configs/traceability.yaml`, `scripts/trace_check.py`: 요구사항마다 실제 시험 노드와 증거 파일을 연결하고 `reports/traceability.md`를 생성한다. 원 요구사항 문서의 시험 경로는 존재하지 않았으므로 이 파일을 정본으로 삼는다.
* 성능 SRP-PHAT은 공간 공분산 `wᴴRw` 형태로 바꿔 방위 격자 반복을 없앴다(호출당 약 26 ms).

## 14. 성능 목표 재도전 (2026-11-21)

* **AuxIVA 시도와 기각(`training/bss.py`)**: 결정형 2화자·4마이크 블라인드 분리를 시험했다. 이상적인 주파수 영역 혼합에서는 완전히 분리했다. 그러나 렌더 장면에서는 SI-SDRi가 −3~+3 dB에 그쳤다. 원인은 비용 함수다. 참값 분리 해의 IVA 비용이 항등 해보다 높았다(모델 불일치). 같은 장면에서 오라클 주파수별 선형 분리는 25 dB, 오라클 마스크 MVDR은 5–8 dB였다. 모듈은 기록용으로 남기고 후보로는 쓰지 않는다.
* **신경망 후보(`training/neural.py`)**: 이 PC에서 CPU용 PyTorch가 로드됨을 확인했다(앞서의 "프레임워크 없음" 차단 해소). 구성은 다음과 같다.
  * 모델: BLSTM 비율 마스크. 입력은 기준 마이크 로그 크기 스펙트럼과, 짝 마이크와의 위상차 cos/sin이다. 2마이크 이상의 어떤 배열에도 쓸 수 있다.
  * 학습: 발화 단위 순열 불변 SI-SDR 손실, 시드 고정(체크포인트 해시 재현).
  * REQ-401 결과: 1시간 고정 벤치마크(360 × 10 s, 학습에 없던 화자·방)에서 SI-SDRi 평균 **8.28 dB**(95 % CI 7.77–8.77)로 목표 8 dB를 넘었다. 평가 시간은 93 s(RTF 0.026)였다. 학습은 4,000 스텝, CPU로 33분이 걸렸다. 근거는 `reports/experiments/req401_neural/`.
  * 주의: 합성 대리 자산 기준이다. CI 하한은 8 dB를 밑돈다.
* **폐루프 보정(`closed_loop_calibrate`)**: 재생성 데이터를 같은 블라인드 추정기로 측정한다. 분위수별 비율로 목표를 보정하고 KL ≤ 0.1까지 반복한다. 렌더러 편향과 추정기 편향을 함께 상쇄한다.
* **REQ-303 신경 모델 재측정(`scripts/run_robustness_experiment.py`)**: 세 번 독립 실행했다(각 3,000 스텝, 실행마다 새 시드). 결과 파일은 `summary_v1/v2/v3.json`.
  * v1(시드 0, 시험 30장면): 방 B = 같은 생성기의 미지 방. 방 B 이득 +0.61 dB. 단일 방 기준 모델도 방 A→B 하락이 거의 없었다(2.79→2.75 dB).
  * v2(시드 1, 시험 60장면): 요구사항 문구("완전히 보지 못한 새로운 도메인", 기기·환경 불일치)에 맞춰 실행 전에 규약을 고정했다. 방 B = 도메인 격차 실험의 대리 실측 영역(미지 재질, 대역 잔향, 4 kHz 기기, 감도 ±2 dB, 잡음). 배열 하락은 같은 미지 방 풀의 circular4 대조군 기준이다(방 A 기준 하락도 함께 보고). 방 B 이득 +0.93 dB(CI −0.17~2.02), 배열 3종 반감 충족.
  * v3(시드 2): 강건 모델에 도메인 무작위화(RT60 0.15–1.2 s 균등, 절반 장면 대역 잔향)를 더했다. 범위는 방 B에 맞추지 않은 일반값이다. 방 B 이득 +0.48 dB(CI −0.47~1.33), 배열 3종 반감은 두 정의 모두에서 충족.
  * 결론: 배열 기준은 충족, 방 B 기준은 미달. 대리 영역의 미지 도메인(흡음 재질)이 반사성 학습 방보다 오히려 쉬워(v3 기준 모델 방 A 1.29 dB, 방 B 3.52 dB) 기준이 가정한 격차가 생기지 않는다. 판정에는 실측 목표 영역이 필요하다. 결과가 나올 때까지 규약을 바꾸는 반복은 하지 않는다.
* **REQ-302 측정 설계 수정**: 첫 폐루프 실행(n=60)은 KL 0.22→0.25로 수렴하지 않았다. 원인은 두 가지였다.
  * 표본 크기: 같은 분포에서 뽑은 n=60 표본 두 개의 KL(0–2 s, 10구간)이 중앙값 0.12, p90 0.33이다. 즉 n=60에서는 보정이 완벽해도 0.1을 판정할 수 없다. n=300에서는 잡음 바닥이 약 0.03이다.
  * 목표 배정: 계획기가 보정 목표를 복원 추출했다. 재생성 집합에 부트스트랩 잡음이 더해졌다. `calibration.assignment: "stratified"`를 추가해 목표마다 한 번씩 렌더한다(기본값 `random`은 그대로).
  * 렌더러 응답: 목표 0.3/0.5/0.8 s → 블라인드 추정 0.28/0.47/0.63 s(장치 열화 유무와 무관). 단조이나 긴 잔향에서 압축된다. 폐루프의 분위수 보정이 이 압축을 상쇄한다.

## 15. 실측·공개 자료 연동 (2026-11-22)

사용자가 승인한 공개 자료 다섯 종을 내려받아 연동했다. 원본과 파생물은 모두 `data/external/` 아래에 두고 버전 관리에서 뺀다.

| 자료 | 라이선스 | 쓰임 |
| --- | --- | --- |
| LibriSpeech dev-clean / test-clean | CC BY 4.0 | 학습 음성(dev-clean), 시험 음성(test-clean). 화자가 겹치지 않는다 |
| DEMAND 16 kHz | CC BY-SA 3.0 | 잡음 자산(환경별 30 s 조각, 1번 채널) |
| AMI (6개 회의, Array1 8채널) | CC BY 4.0 | 실측 방 도메인: dev 2회의 ×2, blind_test 1회의 ×2 |
| HUTUBS SOFA (측정 96명) | CC BY 4.0 | 바이노럴 측정 HRTF |
| Whisper small.en | MIT | 실제 ASR(WER) |

* **가져오기(`datagen/external.py`)**: 압축 해제는 경로 이탈 검사 후에만 한다. LibriSpeech는 발화 단위로 화자·녹음 키와 전사를 붙여 등록한다. DEMAND는 정수 원본 형식 기준으로 실수 변환한다.
* **측정 HRTF(`simulator/hrtf_db.py`)**: SOFA의 `Data.IR`를 16 kHz·128탭으로 재표본화한다. 정면 평균 시작점이 64탭에 오도록 정렬한다(합성 모델과 같은 지연 기준). 방향은 최근접 측정점이다. 수음기 좌표계(전방 +z, 위 +y, 왼귀 +x)로 SOFA (방위, 앙각)를 변환한다. `check_profile`은 `hrtf`가 바이노럴 수음기에만 있고 파일이 존재하는지 검사한다.
* **AMI 중첩 장면(`datatools/ami.py`)**: 실제 회의에는 화자별 참값 신호가 없다. 그래서 같은 회의의 단일 화자 구간 두 개(수동 NXT 단어 주석, 앞뒤 0.5 s 여유, 2.5–6 s)를 Array1 8채널 그대로 더한다. 결과는 실제 방·실제 마이크·실제 잡음의 혼합이다. 각 구간의 원 녹음이 정확한 참값이다(혼합 = 참값 합). 배경 잡음은 두 참값 모두에 들어 있으므로 SI-SDR의 상한을 낮춘다. 위치 참값은 없으므로 DOA는 계산하지 않는다(`geometry.pairs: []`).
* **세션 분할과 블라인드 보호**: 회의 단위로 dev/blind_test를 나눈다(`configs/real_sessions_ami.csv`). 동의는 코퍼스 라이선스로 확인한다. 보정 프로파일(RT60)은 dev 회의에서만 추정한다. blind_test는 dev 비교로 고른 후보의 체크포인트 해시를 `BlindTestGuard`에 고정한 뒤에만 연다.
* **입력 수준 정합(AGC)**: AMI 원 신호는 약 −47 dBFS로 학습 장면보다 훨씬 작다. `NeuralSeparator(input_rms_dbfs=...)`가 기준 채널 RMS를 학습 장면 중앙값(`agc.json`)에 맞춘 뒤 분리하고 이득을 되돌린다. 신경망 시스템 모두에 같은 값을 쓴다.
* **학습 3종(`scripts/run_real_data_experiments.py`)**: 모두 LibriSpeech dev-clean 1,200장면, 20,000 스텝, 시드 0으로 맞췄다.
  * base: 방 하나, 재질 wood, 증강 없음.
  * robust: 배열 3종, 도메인 무작위 RT60 0.15–1.2 s, 잡음 p=0.5, 절반 대역 잔향, 증강.
  * cal: robust와 같되 RT60 목표만 AMI dev 회의의 블라인드 RT60 분포로 바꿨다.
* **판정 규약(실행 전 고정)**: 후보는 dev SI-SDRi 평균이 가장 높은 신경망 모델이다. REQ-303의 방 B 조건은 AMI blind_test에서 기준 모델(base) 대비 후보 이득으로 판정한다. 합성 대리 영역 결과(§14)는 대체하지 않고 함께 기록한다.
* **결과(`reports/experiments/real_v1/`)**: 학습 자료 기준 SI-SDR는 base 4.9 / robust 6.2 / cal 9.1 dB였다. CPU 학습 시간은 각각 4.7 / 3.8 / 5.6 h였다.

  | 평가 | 원음 | base | robust | cal |
  | --- | --- | --- | --- | --- |
  | AMI dev 160장면 SI-SDRi (dB) | 0 | 1.18 | 1.61 | 1.81 |
  | AMI dev DER | 0.74 | 0.50 | 0.45 | 0.43 |
  | AMI dev WER | 0.46 | 0.95 | 0.85 | 0.82 |
  | AMI blind_test 80장면 SI-SDRi (dB) | 0 | 0.16 | — | −1.84 |
  | AMI blind_test DER / WER | 0.75 / 0.51 | 0.56 / 1.05 | — | 0.51 / 1.07 |
  | LibriSpeech 시험 SI-SDRi (dB) / WER | 0 / 0.60 | 1.13 / 0.76 | 1.39 / 0.94 | 0.86 / 0.98 |
  | 미지 배열 SI-SDRi (dB): circular4 / circular3_r3 / linear3_4cm / square4_8cm | — | 0.42 / 0.01 / 0.18 / 0.23 | 0.58 / 0.89 / 0.39 / 0.20 | 0.23 / 0.50 / 0.06 / 0.07 |

  * 사전 규칙대로 dev 1위 cal을 고정한 뒤 blind_test를 열었다. 접근 기록은 dev 1회, 고정 해시로 blind_test 1회다. 결과를 본 뒤 재학습하거나 blind_test를 다시 열지 않는다.
  * REQ-303 방 B 조건(+1.5 dB)은 실측 미지 영역에서도 미달이다. cal은 base보다 −2.00 dB(CI −2.48~−1.53)였다. dev 회의(Edinburgh·IDIAP)로 맞춘 RT60 보정이 다른 장소(TNO)로 옮겨 가지 않았다.
  * 분리는 화자 구간 판정(DER)을 일관되게 개선했다. 반면 Whisper WER은 악화했다. 표본 확인 결과 분리 스트림 두 개에 같은 발화가 함께 남아 단어가 중복 인식된다(삽입 오류).
  * 실음성 분리 성능 자체가 낮다(시험 ≤ 1.8 dB, 학습 자료 4.9–9.1 dB). 40명 화자·1,200장면 학습의 일반화 한계로 본다. 다음 수단은 학습 자료 확대(LibriSpeech train-clean)와 GPU 학습이다. 규약은 그대로 두고 재측정한다.
* **실측 적응(REQ-304, `stage_ami_adapt`)**: 신경 분리기 입력은 주파수 대역마다 (로그 크기, cos, sin) 3차원이다. 그래서 기존 `CoralAdapter`를 그대로 대역별로 쓴다(`training/neural.py::fit_feature_coral`, `NeuralSeparator(adapter=...)`). 재학습은 없다.
  * 원천 통계: 각 모델의 학습 장면 100개.
  * 대상 통계: 라벨 없는 AMI dev-a 혼합음(ES2002a, IS1009a) 80장면.
  * 평가: dev-b(ES2002b, IS1009b) 80장면. blind_test는 열지 않았다.
  * 채택 규칙(실행 전 고정): 같은 모델 대비 SI-SDRi 쌍 비교 95 % CI 하한 > 0.
  * 결과: base −1.34 dB(CI −2.00~−0.70), robust −0.71 dB(CI −1.39~0.02), cal −0.79 dB(CI −1.51~−0.08). DER은 0.01–0.02 개선. 세 모델 모두 채택하지 않는다. IPD의 cos/sin을 선형 재채색하면 공간 단서가 왜곡되는 것으로 본다. 실측 dev에서 적응이 이득을 내지 못함을 확인했다.
* **v2 재학습(`--tag v2`, `reports/experiments/real_v2/`)**: v1 §15 결론의 다음 수단을 실행했다. 시험 세트, AGC 방식, 판정 규약은 v1과 같다.
  * 학습 음성: LibriSpeech train-clean-100(발화 ≤ 16 s, 화자당 ≤ 40개, 10,025개) + dev-clean, 291명. 모델당 1,800장면.
  * 학습: GPU(RTX 2060 SUPER, torch 2.15+cu132), 배치 16, 30,000 스텝, 스레드 배치 생성기 6개(`train_net(loader_threads=6)`, 단계 번호로 시드를 나눠 재현 가능).
  * 학습 시간: base 1.3 / robust 1.8 / cal 1.8 h. 학습 자료 기준 SI-SDR: 6.6 / 7.0 / 8.7 dB.
  * 알려진 문제: 이 torch/cuDNN 9.26 조합에서 드롭아웃이 있는 다층 LSTM을 학습한 프로세스는 종료 처리 중 0xC0000409로 끝난다(체크포인트 저장 뒤). 단독 재현으로 원인을 cuDNN 드롭아웃 상태로 좁혔다. 학습 스크립트는 CUDA 학습 단계 뒤 종료 처리를 건너뛴다.

  | 평가 | 원음 | base v1 → v2 | robust v1 → v2 | cal v1 → v2 |
  | --- | --- | --- | --- | --- |
  | AMI dev 160장면 SI-SDRi (dB) | 0 | 1.18 → −0.05 | 1.61 → 0.54 | 1.81 → 1.41 |
  | AMI dev DER | 0.74 | 0.50 → 0.53 | 0.45 → 0.48 | 0.43 → 0.44 |
  | AMI dev WER | 0.46 | 0.95 → 0.87 | 0.85 → 0.86 | 0.82 → 0.86 |
  | LibriSpeech 시험 SI-SDRi (dB) | 0 | 1.13 → 0.59 | 1.39 → 1.86 | 0.86 → 1.91 |
  | LibriSpeech 시험 WER (원음 0.60) | — | 0.76 → 1.10 | 0.94 → 0.87 | 0.98 → 0.94 |
  | 미지 배열 SI-SDRi 최대 (dB) | — | 0.42 → 0.52 | 0.89 → 1.61 | 0.50 → 1.54 |

  * 화자를 늘리자 증강 모델(robust, cal)은 LibriSpeech 시험과 미지 배열에서 좋아졌다. 반면 base는 나빠졌다.
  * AMI dev에서는 세 모델 모두 v1보다 낮다. dev 1위는 여전히 cal이다(1.41 dB). 절대값으로는 v1 cal(1.81 dB)이 더 높다.
  * AMI dev에서 cal은 base보다 +1.46 dB(CI 0.90~2.06)였다(v1은 +0.63, CI 0.15~1.15).
  * 이 값은 REQ-303 판정이 아니다. dev는 보정 프로파일을 추정한 회의라 미지 영역이 아니다. 게다가 v1에서 dev +0.63이 blind_test에서 −2.00으로 뒤집혔다.
  * blind_test(TS3003a/b)는 v1 후보가 이미 한 번 열었으므로 다시 열지 않았다. REQ-303을 공정하게 판정하려면 새 미지 AMI 회의가 필요하다(내려받기 허가 필요).
  * Whisper WER은 v2에서도 분리 후가 원음보다 나쁘다(REQ-305 미달 유지).
* **v2 실측 적응(같은 규칙, `real_v2/ami_adapt.json`)**: dev-a 혼합음으로 맞추고 dev-b 80장면에서 측정했다.

  | 모델 | 적응 없음 (dB) | +CORAL (dB) | 쌍 차이 (95 % CI) | 채택 |
  | --- | --- | --- | --- | --- |
  | base | 0.26 | −0.58 | −0.85 (−1.53~−0.20) | 아니오 |
  | robust | 0.93 | 1.67 | +0.74 (0.08~1.36) | 예 |
  | cal | 1.27 | 1.76 | +0.49 (−0.13~1.15) | 아니오 |

  * 사전 규칙상 robust+CORAL은 채택된다. v1에서는 세 모델 모두 손해였다. 증강으로 학습한 모델만 이득을 본다.
  * 그래서 "IPD의 cos/sin을 선형 재채색하면 공간 단서가 망가진다"는 v1 해석은 일반화할 수 없다. 이득 여부는 모델의 학습 분포에 달렸다.
  * 주의: 세 모델을 각각 시험했다. 다중 비교를 보정하면(Bonferroni 3회, 98.3 % CI) robust의 구간은 −0.05~1.49 dB로 0을 포함한다. 그래서 REQ-304는 "실측에서 증강 모델에 한해 이득 신호, 새 회의로 재확인 필요"로 기록한다.
* **우세 화자 게이트 WER(2026-11-22, `asr_gate` 단계, `real_v*/asr_gate.json`)**: 분리 스트림은 상대 화자를 흘려서 같은 단어가 두 스트림에서 두 번 인식된다. 결과를 보기 전에 규칙을 코드로 고정했다.
  * 규칙: Whisper를 단어 타임스탬프 모드로 돌린다. 단어 중점이 자기 스트림의 화자 구간(`diarize_streams`, ±0.1 s) 안에 있을 때만 남긴다. 서로 다른 스트림이 둘 미만이면 게이트하지 않는다. 그래서 원음(같은 혼합음 사본)은 바뀌지 않는다. 모든 시스템에 같게 적용한다.
  * 단어 타임스탬프 모드는 디코딩 자체를 바꾼다. 그래서 원음 WER도 일반 실행과 다르다(AMI dev 0.46 → 0.446, LibriSpeech 0.60 → 0.455). 비교는 같은 실행 안에서만 한다.

  | AMI dev 160장면 WER | 원음 | base | robust | cal | cal − base (%p, 95 % CI) |
  | --- | --- | --- | --- | --- | --- |
  | v1 일반 → 게이트 | 0.446 | 0.89 → 0.75 | 0.83 → 0.67 | 0.77 → 0.66 | −8.9 (−15.0~−3.8) |
  | v2 일반 → 게이트 | 0.446 | 0.87 → 0.76 | 0.83 → 0.68 | 0.79 → 0.68 | −7.8 (−12.3~−2.6) |

  * 게이트는 분리 시스템의 WER을 11~16 %p 낮춘다. 그래도 모든 분리 시스템이 원음(0.446)보다 나쁘다. REQ-402 WER 조건은 여전히 미달이다.
  * REQ-305 수치 조건(cal − base ≤ −3.0 %p, CI 상한 < 0)은 AMI dev 게이트 WER에서 v1, v2 모두 맞는다. 그러나 dev는 미지 영역이 아니고 세션이 4개다. 판정은 보류한다(20세션 미만). 요인표는 `reports/experiments/req305/attribution.md`.
  * blind_test는 열지 않았다.
* **새 blind 회의(2026-11-22)**: AMI 20회의(ES2004, ES2014, IS1006, IS1003 a·c·d, IS1007a, TS3007)를 `E:\audioSeperation\data\external\ami`에 받았다. 그런데 세션 분할 규칙(`real_sessions.DEFAULT_GROUP_KEYS = ("room", "speaker")`)은 방(=AMI 녹음 장소)이 dev와 겹치면 blind로 쓸 수 없게 한다. dev가 Edinburgh(ES)와 IDIAP(IS) 방을 쓰므로 새 blind 자격은 TNO 방의 TS3007a~d 4회의뿐이다. 20세션 blind를 만들려면 TNO 회의 16개(TS3004, TS3005, TS3006, TS3008 a~d, 약 9.3 GB)가 더 필요하다(사용자 승인 대기). ES/IS 16회의는 dev 보강 자료로만 쓸 수 있다.
* **blind2 판정 규약(2026-11-22, blind2 자료를 처리하기 전에 고정)**
  * 세션: 이전에 쓰지 않은 AMI TNO(TS) 회의다. 화자는 지금까지 쓴 모든 회의와 겹치지 않는다. 방은 dev(Edinburgh·IDIAP)와 겹치지 않는다. 지금은 TS3007a~d다. 내려받기가 승인되면 TS3004·TS3005·TS3006·TS3008 a~d를 더한다. 디스크에 있는 목록 회의는 모두 넣는다(결과를 보고 고르지 않는다). TS3003은 이미 한 번 열었으므로 뺀다.
  * 등록부: `configs/real_sessions_ami_blind2.csv`. dev는 ES2002a/b, IS1009a/b 그대로이고, blind_test는 새 회의다. 분할 누수 검사(방+화자)를 통과해야 만든다.
  * 장면: 같은 생성기(`build_meeting_scenes`), 회의당 40장면, 난수 시드 100.
  * 후보: 학습한 모든 모델(v1, v2) 가운데 AMI dev SI-SDRi 평균이 가장 높은 모델이다(저장된 dev 결과로 정한다. 현재 v1 cal 1.81 dB). 기준은 같은 버전의 base다. 다른 버전의 cal−base는 참고로만 보고하고 판정하지 않는다.
  * ASR: Whisper small.en, 단어 타임스탬프. REQ-305·REQ-402의 주 지표는 게이트하지 않은 WER이다. 게이트 WER은 보조로 보고한다.
  * 판정
    * REQ-303 방 B: 후보 − 기준 SI-SDRi 평균 ≥ +1.5 dB.
    * REQ-305: §6.2 그대로다. 후보 − 기준 WER ≤ −3.0 %p이고, 세션별 차이의 부트스트랩 95 % CI 상한 < 0이다. 세션 20개 미만이면 보류한다.
    * REQ-402: 원음 대비 WER 상대 −15 % 이상, DER −5.0 %p 이상.
  * 열기: 후보 체크포인트 해시를 `BlindTestGuard`에 고정한 뒤 한 번만 연다. 접근 기록(`reports/experiments/ami_blind2/access_log.json`)이 있으면 다시 열기를 거부한다. 회의를 더 받으면 같은 후보로 전체(기존+추가)를 한 번 다시 평가할 수 있다. 이때 모델·규칙은 바꾸지 않는다.
* **blind2 1차(TS3007a~d, 4세션 160장면, `reports/experiments/ami_blind2/result_ts3007.json`)**: 규약대로 dev 1위 v1 cal을 고정했다(해시 b4cf6161…). 기준은 v1 base다.

  | 시스템 | SI-SDRi (dB) | DER | WER | 게이트 WER |
  | --- | --- | --- | --- | --- |
  | 원음 | 0 | 0.756 | 0.540 | 0.540 |
  | v1 cal (후보) | −0.80 | 0.530 | 0.872 | 0.769 |
  | v1 base (기준) | 0.20 | 0.535 | 0.865 | 0.758 |
  | v2 cal (참고) | −0.16 | 0.542 | 0.960 | 0.874 |
  | v2 base (참고) | −0.58 | 0.563 | 0.865 | 0.803 |

  * REQ-303: 후보 − 기준 −1.00 dB(세션 CI −1.24~−0.79). +1.5 dB에 못 미친다.
  * REQ-305: +0.67 %p(CI −4.2~+4.1). 4세션이라 보류한다.
  * REQ-402: DER은 −22.6 %p로 맞지만, WER이 원음보다 61 % 나빠 미달이다.
  * TNO 회의 16개를 받은 뒤 같은 후보로 20세션 전체를 한 번 평가한다(규약상 허용되는 마지막 열기).
* **blind2 최종(20세션 800장면, 2026-11-23, `reports/experiments/ami_blind2/result.json`)**: TS3004·TS3005·TS3006·TS3007·TS3008 a~d다. 후보(v1 cal, 해시 b4cf6161…)와 규칙은 1차와 같다. 이것이 규약상 마지막 열기이며, 접근 기록에 두 번(4세션, 20세션)이 남아 있다.

  | 시스템 | SI-SDRi (dB) | DER | WER | 게이트 WER |
  | --- | --- | --- | --- | --- |
  | 원음 | 0 | 0.771 | 0.504 | 0.504 |
  | v1 cal (후보) | −0.11 | 0.509 | 0.870 | 0.756 |
  | v1 base (기준) | 0.26 | 0.544 | 0.880 | 0.745 |
  | v2 cal (참고) | 0.12 | 0.512 | 0.883 | 0.797 |
  | v2 base (참고) | −0.23 | 0.557 | 0.873 | 0.778 |

  * REQ-303 **미달**: 후보 − 기준 −0.37 dB(세션 CI −0.67~−0.05). 목표 +1.5 dB에 못 미치고, CI가 0보다 아래다.
  * REQ-305 **미달**: −1.08 %p(세션 CI −3.51~+1.59). 20세션이라 보류하지 않는다. −3.0 %p와 CI 상한 < 0을 둘 다 못 맞춘다. 게이트 WER(보조)은 +1.10 %p(CI −1.10~+3.09)다.
  * REQ-402 **미달**: DER은 0.771 → 0.509(−26.2 %p)로 맞는다. WER은 0.504 → 0.870(상대 +72 %)으로 원음보다 나쁘다.
  * 참고(판정 안 함): v2 cal − v2 base는 +0.34 dB(CI −0.28~+0.85)다. dev에서 본 +1.46 dB가 미지 회의에서는 거의 사라진다. 처음 받은 4세션(TS3007)을 빼고 새 16세션만 보면 v1 cal − base는 −0.22 dB(CI −0.59~+0.14)로, 방향이 같다.
  * 해석: 분리 모델 4개 모두 미지 방(TNO)에서 원음 대비 SI-SDRi가 −0.23~+0.26 dB다. 사실상 분리가 일어나지 않는다. DER이 좋아지는 것은 스트림이 둘로 나뉘어 화자 구간이 잡히기 때문이다. 하지만 각 스트림에 다른 화자가 그대로 남아 WER은 나빠진다. dev(Edinburgh·IDIAP)에서 본 개선(+1.2~1.8 dB, 게이트 WER −8.9 %p)은 방이 다르면 이어지지 않는다. 지금 모델·학습 자료(LibriSpeech 합성 장면, 보정·증강 포함)로는 REQ-303·305·402를 맞출 수 없다는 것이 사전 규약에 따른 결론이다.
  * 다음 시도는 모델·자료를 바꾸는 새 실험이다. 판정에는 아직 열지 않은 미지 회의가 필요하다. blind2에 쓴 TS3004~TS3008은 다시 쓰지 않는다. 아직 열지 않은 AMI TNO 회의 TS3009~TS3012(16회의, 약 8 GB)가 남아 있다. 다만 blind2와 같은 TNO 방이므로, 새 모델은 blind2 결과를 보고 TNO에 맞추어 고치면 안 된다. 다른 장소의 코퍼스를 쓰는 방법도 있다. 무엇을 blind3로 할지와 내려받기는 사용자 승인이 필요하다.

## 16. v3 실측 혼합 학습과 blind3 판정 규약 (2026-11-23, 학습·blind3 처리 전에 고정)

사용자가 2026-11-23 "새 모델 + blind3"를 승인했다. 승인에는 TNO 회의 TS3009~TS3012 내려받기도 들어 있다. 아래 내용은 v3 학습을 시작하기 전, 그리고 blind3 자료를 처리하기 전에 정했다. 결과를 본 뒤에는 바꾸지 않는다. 같은 내용을 `reports/experiments/ami_blind3/preregistration.json`에 기계가 읽는 형태로 둔다.

* **바꾸는 것(가설)**: v1·v2는 합성 장면만으로 학습했다. 그래서 실제 방·마이크 체인에서는 분리가 거의 되지 않았다(blind2, −0.23~+0.26 dB). v3는 실제 AMI 녹음을 학습 자료에 넣는다. REQ-301의 합성·실측 혼합 학습을 실측 자료로 실행하는 것이다.
* **실측 학습 자료**: AMI ES·IS 회의 16개다(처음에 17개로 잘못 세었다. 목록은 처음 그대로다). ES2004a~d, ES2014a~d, IS1003a·c·d, IS1006a~d, IS1007a이다.
  * 방은 Edinburgh와 IDIAP다. 화자 20명은 dev(ES2002a/b, IS1009a/b)와 모든 blind 회의(TS3003~TS3012)의 화자와 겹치지 않는다. 2026-11-23에 확인했다.
  * TNO 회의는 학습·보정·선택 어디에도 쓰지 않는다.
  * 장면은 같은 생성기(`build_meeting_scenes`)로 만든다. 회의당 80장면, 회의별 난수 시드는 `[300, 회의 번호, 회의 글자]`다.
  * 메모리 때문에 Array1 마이크 1(기준)·2·8(기준에 가장 가까운 두 개)만 학습에 쓴다. 추론할 때 짝 마이크는 지금처럼 가장 가까운 마이크다.
  * 실측 장면은 추론 때와 같은 AGC 목표(v2 `agc.json`) 수준으로 맞춘다. 혼합음과 참조를 같은 이득으로 키운다.
* **모델 두 개**: 구조와 학습 설정은 v2와 같다. 새로 학습하고, 30,000 스텝, 배치 16, 4 s 구간, GPU, 증강을 켠다.
  * v3-mix: 실측 AMI 학습 장면 50 %, v2 robust 합성 장면 50 %.
  * v3-real: 실측 AMI 학습 장면 100 %.
* **후보 선정**: v3-mix와 v3-real 가운데 AMI dev 160장면의 SI-SDRi 평균이 높은 쪽이다. dev는 학습 자료와 방이 같으므로 dev 수치는 낙관적이다. dev는 선정에만 쓰고 판정에는 쓰지 않는다.
* **기준 모델**: v2 base(합성 방 하나로만 학습, 증강 없음). REQ-303의 "방 A로 학습한 기준 모델"이다. v1 base, v2 cal, v3의 다른 모델은 참고로만 보고한다.
* **blind3 세션**: TS3009~TS3012 a~d, 16세션이다(TNO 방, 화자는 처음 보는 사람이다). 장면은 회의당 40개, 시드는 blind2와 같은 규칙(`[100, 회의 번호, 회의 글자]`)이다. 등록부는 `configs/real_sessions_ami_blind3.csv`다. 방·화자 누수 검사를 통과해야 만든다.
* **판정**(설계 §6.2, 2026-11-23 승인 규칙)
  * REQ-303: 후보 − 기준 SI-SDRi 평균 ≥ +1.5 dB. 세션 부트스트랩 CI를 함께 보고한다.
  * REQ-305: 후보 − 기준 WER ≤ −3.0 %p, 세션 CI 상한 < 0.
  * REQ-402: 원음 대비 WER 상대 −15 % 이상, DER −5.0 %p 이상.
  * 승인된 규칙은 세션이 20개 미만이면 WER·DER 판정을 보류한다. blind3는 16세션이므로 REQ-305·REQ-402는 수치만 보고하고 보류로 적는다. 결과를 보기 전에 정한 것이다. REQ-303은 §6.2 게이트 지표가 아니므로 16세션으로 판정한다.
  * ASR은 Whisper small.en, 단어 타임스탬프다. 주 지표는 게이트하지 않은 WER이고, 게이트 WER은 보조다.
* **열기**: 후보 체크포인트 해시를 `BlindTestGuard`에 고정한 뒤 한 번만 연다. 접근 기록은 `reports/experiments/ami_blind3/access_log.json`이다. 다시 열기는 없다.

### 16.1 결과 (2026-11-24, blind3 한 번 열기)

* **학습**: 두 모델 모두 30,000 스텝을 GPU에서 마쳤다(각 약 1시간 55분). 실측 AMI 학습 장면 1,280개(16회의 × 80), 합성 장면 1,800개를 썼다. 마지막 학습 SI-SDR은 v3-mix 3.36 dB, v3-real 6.02 dB다.
* **AMI dev 선정**(160장면, 4세션)

  | 시스템 | SI-SDRi (dB) | DER | WER | 게이트 WER |
  | --- | --- | --- | --- | --- |
  | 원음 | 0 | 0.743 | 0.446 | 0.446 |
  | v2 base (기준) | −0.05 | 0.530 | 0.866 | 0.760 |
  | **v3-mix** | **3.97** | 0.314 | 0.699 | 0.580 |
  | v3-real | 3.06 | 0.307 | 0.605 | 0.540 |

  규칙대로 dev SI-SDRi가 높은 v3-mix를 후보로 고정했다. 해시는 `39e9a93e…`다. dev는 학습 회의와 방이 같아 낙관적인 값이다.
* **blind3 판정**(TS3009~TS3012 a~d, 16세션, 640장면, 한 번 열었다)

  | 시스템 | SI-SDRi (dB) | DER | WER | 게이트 WER |
  | --- | --- | --- | --- | --- |
  | 원음 | 0 | 0.774 | 0.508 | 0.508 |
  | **v3-mix (후보)** | **3.02** | 0.364 | 0.798 | 0.648 |
  | v2 base (기준) | −0.34 | 0.583 | 0.910 | 0.818 |
  | v3-real (참고) | 2.83 | 0.323 | 0.687 | 0.620 |
  | v2 cal (참고) | 0.07 | 0.521 | 0.900 | 0.814 |
  | v1 base (참고) | 0.39 | 0.563 | 0.883 | 0.755 |

  * REQ-303 **충족**: 후보 − 기준 +3.36 dB(세션 CI +2.99~+3.75). 목표는 +1.5 dB다. 참고로 v3-real − 기준은 +3.17 dB(CI +2.67~+3.68)다.
  * REQ-305 **보류**(16세션 < 20): −11.25 %p(세션 CI −13.34~−9.12)다. 세션 수 외의 수치 조건(−3.0 %p 이하, CI 상한 < 0)은 맞는다. 게이트 WER(보조)은 −16.98 %p(CI −18.20~−15.74)다. 정식 통과에는 아직 열지 않은 20세션 이상이 필요하다.
  * REQ-402 **보류, 미달 유지**: DER 0.774 → 0.364(−41.1 %p)로 DER 조건은 맞는다. WER은 0.508 → 0.798(상대 +57 %)로 원음보다 나쁘다. 세션 수와 관계없이 WER 조건(−15 %)에 크게 못 미친다. 그래서 추적표 상태는 미달로 둔다.
* **해석**
  * 실제 녹음을 학습에 넣자 처음으로 미지 회의에서 분리가 일어났다. 원음 대비 +3.0 dB이고, 합성만 쓴 모델(−0.34~+0.39 dB)과 확연히 다르다. 같은 TNO 방을 쓴 blind2에서는 v1·v2 모두 −0.23~+0.26 dB였다.
  * 기준 모델(v2 base) 대비 WER도 11 %p 낮아졌다. 하지만 분리한 스트림을 Whisper로 읽으면 여전히 원음보다 나쁘다. 남은 다른 화자 소리와 마스크 왜곡이 원인이다.
  * dev 1위(v3-mix)와 blind3 1위(SI-SDRi 기준 v3-mix, WER 기준 v3-real)가 일치한다. 실측 비중이 높은 v3-real은 SI-SDRi가 조금 낮지만 WER·DER은 더 낫다. 판정은 사전 규칙대로 v3-mix로만 한다.
* **한계**
  * blind3는 blind2와 방이 같다(TNO, 화자는 다르다). 다른 장소에서의 일반화는 아직 확인하지 않았다.
  * 기준 모델 자체가 원음보다 −0.34 dB다. 원음 대비 이득(+3.02 dB)도 함께 본다.
  * 이 결과를 보고 모델·규칙을 바꾸지 않았다. TS3003·blind2·blind3는 모두 은퇴했고 다시 열지 않는다.
* **기록**: `reports/experiments/ami_blind3/result.json`, `access_log.json`(열기 1회), `build.json`, `reports/experiments/real_v3/ami_eval.json`, `configs/traceability.yaml`.
* **자료 무결성**: TS3009~TS3012 내려받기 중 서버 오류 페이지가 파일 6개에 섞였다. 크기는 서버 값과 같아 크기 검사로는 잡히지 않았다. blind3 장면 생성이 RIFF 머리글 오류로 멈추면서 드러났다. 6개를 다시 받았고, AMI 58회의 전체에 HTML 혼입이 없는지 확인한 뒤 장면을 만들었다. 이후 내려받기 스크립트는 HTTP 오류에서 실패하도록(`curl -f`) 고쳤다.

## 17. REQ-402 WER 지표 진단 (2026-11-24, 실행 전에 고정)

blind3에서 v3-mix는 SI-SDRi +3.0 dB, DER −41 %p로 분리가 되는데도 WER은 원음보다 57 % 나빴다. 원인 후보는 두 가지다.

* **분리기**: 남은 다른 화자 소리와 마스크 왜곡 때문에 Whisper가 틀린다.
* **지표**: 장면의 참조 문장은 "화자 A 문장 + 화자 B 문장"이다. 그런데 분리 스트림의 단어는 시간순으로 합쳐 비교한다. 두 화자가 20~60 % 겹치므로, 완벽하게 분리해도 겹친 구간의 단어가 엇갈려 순서 오류가 된다. 원음은 스트림이 하나라 이 불이익이 작다.

**진단 방법**(AMI dev 160장면만 쓴다. blind 자료는 열지 않는다)

* 완벽 분리 시스템 `oracle`을 더한다. 각 화자의 실제 참조 신호를 그대로 내놓는다.
* 모든 시스템을 지금 지표(시간순 결합 WER)와 cpWER로 함께 잰다.
  * cpWER는 CHiME-6·MeetEval의 화자별 연결 최소 순열 WER이다. 스트림마다 단어를 자기 시간순으로 잇고, 화자별 참조 문장과 오류가 가장 적은 짝으로 맞춘다. 스트림이 모자라면 삭제, 남으면 삽입으로 센다.
  * 화자별 참조 문장은 장면을 만든 주석 구간에서 다시 얻는다. 둘을 이으면 원래 장면 문장과 같아야 한다(다르면 중단).
* Whisper small.en, 단어 타임스탬프, GPU. 한 번의 인식 결과로 두 지표를 모두 계산한다.

**판단 규칙**(결과를 보기 전에 고정)

* oracle의 시간순 결합 WER이 원음보다 상대 15 % 이상 좋지 않으면, 지금 지표는 완벽한 분리도 REQ-402 기준으로 인정하지 못한다. 이 경우 지표가 REQ-402 판정에 맞지 않는다고 결론짓고, cpWER로 바꾸는 안을 제품 책임자에게 낸다.
* 위 조건이 아니면 지표는 유지하고, 원인을 분리기 쪽으로 본다.
* 어느 쪽이든 승인된 §6.2 규칙은 승인 없이 바꾸지 않는다. 지표를 바꾸더라도 REQ-402 정식 판정은 아직 열지 않은 20세션 이상에서 한다. blind3·blind2 결과를 새 지표로 다시 판정하지 않는다(참고 수치로도 계산하지 않는다).

### 17.1 결과 (2026-11-24, AMI dev 160장면, Whisper small.en GPU)

| 시스템 | SI-SDRi (dB) | 지금 WER(시간순 결합) | cpWER | 게이트 cpWER |
| --- | --- | --- | --- | --- |
| 원음 | 0 | 0.446 | 0.838 | 0.838 |
| v2 base | −0.05 | 0.866 | 0.929 | 0.844 |
| v3-mix | 3.97 | 0.699 | 0.718 | 0.633 |
| v3-real | 3.06 | 0.605 | 0.653 | 0.623 |
| **oracle(완벽 분리)** | — | **0.484** | **0.360** | 0.351 |

원음 대비 차이(세션 4개 부트스트랩 CI)는 다음과 같다.

* oracle: 지금 WER +3.8 %p(CI +0.9~+6.5), cpWER −47.8 %p(CI −51.2~−45.6).
* v3-mix: 지금 WER +25.3 %p, cpWER −12.0 %p(CI −16.6~−7.4).
* v3-real: 지금 WER +16.0 %p, cpWER −18.5 %p(CI −23.3~−14.2).

**판단(§17 규칙 적용)**

* 완벽 분리(oracle)도 지금 지표에서는 원음보다 8.5 % 나쁘다(0.484 vs 0.446). 규칙의 조건(상대 15 % 이상 개선)에 한참 못 미친다. 그래서 지금 지표는 REQ-402 판정에 맞지 않는다고 결론짓는다. blind2·blind3의 REQ-402 WER 미달은 상당 부분 지표 탓이다.
* 원음의 cpWER(0.838)이 높은 것은 스트림이 하나뿐이라 한 화자의 말을 모두 놓친 것으로 세기 때문이다. 이것이 다화자 인식에서 쓰는 표준 정의다(분리하지 않으면 누가 말했는지 모른다).
* oracle의 cpWER도 0.36이다. 잔향이 있는 원거리 단일 화자 음성에서 Whisper small.en이 내는 오류로, 분리로는 줄일 수 없는 하한이다.
* 분리기 쪽 문제도 남아 있다. v3-mix의 cpWER(0.718)은 oracle(0.360)과 거리가 멀다.

**제안(제품 책임자 승인 필요, 승인 전에는 §6.2 그대로)**

* REQ-305와 REQ-402의 WER을 cpWER로 정의한다. 임계값(−3.0 %p, 상대 −15 %, 20세션, CI 규칙)은 그대로 둔다.
* 정식 판정은 아직 열지 않은 새 장소 자료 20세션 이상에서 한다. 판정 전에 후보 선정 규칙(dev 기준)을 다시 사전 등록한다.
* 참고로 dev에서 v3-mix의 cpWER은 원음 대비 상대 −14.3 %, v3-real은 −22.1 %다. dev는 학습 자료와 방이 같아 낙관적이다. 이 수치로 후보를 바꾸지 않았다.

### 17.2 승인 (2026-11-24)

* 사용자(제품 책임자)가 cpWER 안을 승인했다. `configs/decision_rules.yaml`의 `wer_vs_fixed_baseline`, `wer_vs_unprocessed` 지표를 `cpwer`로 바꾸고 개정 기록(`amendments`)을 남겼다. §6.2 표 아래에도 적었다.
* 임계값·20세션·CI 규칙은 그대로다. blind2·blind3에는 소급하지 않는다. REQ-405 회귀 규칙은 개정 범위 밖이다.
* 같은 날 사용자는 새 장소 자료 후보 NOTSOFAR-1의 내려받기 크기 확인을 승인했다. 내려받기 자체는 크기를 알린 뒤 다시 승인을 받는다.

## 18. blind4: 새 장소 NOTSOFAR-1 판정 규약 (2026-11-24, 내려받기·처리 전에 고정)

사용자가 2026-11-24 cpWER 개정(§17.2)과 NOTSOFAR-1 30회의(2.49 GB) 내려받기를 승인했다. 아래 내용은 내려받기 전에 정했다. 결과를 본 뒤에는 바꾸지 않는다. 기계가 읽는 사본은 `reports/experiments/blind4_notsofar/preregistration.json`이다.

* **목적**: REQ-305·REQ-402를 개정 규칙(cpWER)으로 정식 판정한다. REQ-303은 새 장소(AMI 밖)에서 다시 판정한다.
* **자료**: NOTSOFAR-1(Microsoft, CC BY 4.0) `benchmark-datasets/eval_set/240825.1_eval_full_with_GT`의 회의 번호 순 앞 30개(MTG_32000~MTG_32053)다.
  * 회의마다 7채널 원형 장치 `mc_plaza_0` 하나와 `gt_transcription.json`, `gt_meeting_metadata.json`, `devices.json`만 받는다.
  * 실제 회의실 녹음이고, 방·화자·장비가 AMI와 다르다. NOTSOFAR는 학습·보정·선택 어디에도 쓰지 않았다.
* **장면**: AMI와 같은 방법(`build_meeting_scenes`)이다.
  * 정답 단어 시각으로 한 사람만 말하는 구간을 찾는다(2.5~6 s, 단어 4개 이상, 앞뒤 0.5 s 안에 다른 사람 발화 없음). 다른 사람의 발화 구간은 정답 발화의 시작·끝 시각이다.
  * 다른 두 화자의 구간을 20~60 % 겹치게 더한다. 회의당 최대 40장면, 시드는 `[400, 회의 번호]`다.
  * 세션은 회의다. 장면이 10개 이상인 회의만 세션으로 센다. 20세션 미만이면 REQ-305·402는 보류다.
* **배열 가정**(공개 자료에 반지름·채널 순서가 없어 미리 정한다): ch0이 가운데, ch1~ch6이 반지름 4.25 cm 원 위에 있다고 둔다. 기준 마이크는 ch0, 분리기의 짝 마이크는 가장 가까운 마이크 규칙에 따라 ch1이다. 순서 가정이 틀려도 ch0–ch1 간격은 4.25 cm 또는 8.5 cm다. 학습한 AMI 배열의 짝 간격은 7.65 cm다.
* **시스템**: 후보는 v3-mix다(해시 `39e9a93e…`, blind3 전에 AMI dev SI-SDRi 규칙으로 고정). 다시 고르지 않는다. dev cpWER은 v3-real이 더 낫지만, 결과를 본 뒤 후보를 바꾸지 않는다. 기준은 v2 base, 비교는 원음이다. v3-real, v1 base는 참고다.
* **ASR**: Whisper small.en, 단어 타임스탬프, GPU.
* **판정**
  * REQ-303: 후보 − 기준 SI-SDRi 세션 평균 ≥ +1.5 dB, 세션 CI 보고. blind4가 새 장소에서 한 판정이므로 REQ-303 상태는 이 결과로 갱신한다(미달이면 미달).
  * REQ-305·REQ-402: 승인된 `configs/decision_rules.yaml`을 `evaluation/gate.decide`로 그대로 적용한다. 회의별 평균을 세션 값으로 쓴다.
    * REQ-305: 후보 − 기준 cpWER ≤ −3.0 %p, CI 상한 < 0, 20세션 이상.
    * REQ-402: 원음 대비 cpWER 상대 ≤ −15 %이고 CI 상한 < 0, DER ≤ −5.0 %p이고 CI 상한 < 0, 20세션 이상.
    * REQ-405 회귀 규칙(WER)도 같이 계산해 보고한다.
* **열기**: 후보 해시를 고정하고 한 번만 연다. 접근 기록은 `reports/experiments/blind4_notsofar/access_log.json`이다.

### 18.1 사전 등록 개정 (2026-11-24, blind4 평가 전)

* 30회의로 장면을 만든 결과, 장면 10개 이상인 회의가 17개였다. 20세션에 못 미친다. 자연스러운 회의라 다른 사람 발화가 0.5 s 안에 없는 한 사람 구간이 적기 때문이다.
* 이 판단에는 장면 개수만 썼다. blind4 장면에 어떤 시스템도 돌리지 않았다.
* 사용자 승인(2026-11-24)을 받아 같은 eval 세트의 다음 회의 20개(MTG_32054~MTG_32081, 1.62 GB)를 번호 순서대로 더한다. blind4는 앞 50회의가 된다.
* 장면 10개 기준, 20세션 기준, 시드 규칙, 후보, 판정 규칙은 그대로다. 기준을 낮춰 세션 수를 맞추지 않았다.

### 18.2 blind4 결과 (2026-11-24, 한 번 열어 판정)

* **실행**: 후보 v3-mix(해시 `39e9a93eebd5…`)를 고정하고 blind4를 한 번 열었다. 24세션(5개 방 nsf-ROOM_10030/32/33/34/35), 652장면, 5개 시스템, Whisper small.en(GPU, 단어 타임스탬프)으로 평가했다. 접근 기록은 `access_log.json` 한 건이다.
* **사고와 처리**: 평가를 마치고 `eval/comparison.json`(3,260행 = 652장면 × 5시스템)을 쓴 다음, `result.json`을 쓰다가 멈췄다. 승인 규칙의 개정 날짜(YAML `date`)를 JSON으로 바꾸지 못했기 때문이다.
  * 판정은 저장된 행과 승인 규칙만으로 정해지는 계산이다. 그래서 `blind4_finalize` 단계를 추가했다. 이 단계는 접근 기록의 해시와 `comparison.json`의 해시가 같은지 확인하고, 저장된 행에서 `result.json`만 다시 쓴다.
  * 이 단계는 오디오를 읽지 않고 모델도 돌리지 않는다. blind4를 다시 연 것이 아니다. 규칙·후보·세션은 그대로다.
  * 같은 고장을 막는 시험 `test_blind4_result_serialises_rule_amendment_dates`를 추가했다.

장면 평균(652장면):

| 시스템 | SI-SDRi (dB) | cpWER | WER(시간순 결합, 참고) | DER |
|---|---|---|---|---|
| 원음 | 0.00 | 0.821 | 0.433 | 0.922 |
| **v3-mix (후보)** | **+0.37** | **0.916** | 0.847 | **0.593** |
| v2 base (기준) | −0.50 | 0.929 | 0.847 | 0.696 |
| v3-real (참고) | +1.72 | 0.728 | 0.687 | 0.463 |
| v1 base (참고) | +0.08 | 0.877 | 0.858 | 0.662 |

판정(세션 평균, `gate.decide`, 승인 규칙 그대로):

| 요구 | 규칙 | 결과 | 판정 |
|---|---|---|---|
| REQ-303 | 후보 − 기준 SI-SDRi ≥ +1.5 dB | +0.93 dB (CI +0.49..+1.40) | **미달** |
| REQ-305 | 후보 − 기준 cpWER ≤ −3.0 %p, CI 상한 < 0 | 0.908 vs 0.959, −5.15 %p (CI −12.07..+1.92) | **보류(유의하지 않음)** |
| REQ-402 cpWER | 원음 대비 상대 ≤ −15 %, CI 상한 < 0 | 0.823 → 0.908, +10.4 % (CI +0.5..+16.8 %p) | 미달 |
| REQ-402 DER | 원음 대비 ≤ −5.0 %p, CI 상한 < 0 | 0.920 → 0.593, −32.7 %p (CI −35.6..−30.0) | 통과 |
| REQ-402 | 두 조건 모두 | | **미달** |
| REQ-405 | 기준 대비 WER 악화 < 0.5 %p | −3.55 %p | 통과 |

참고 비교(세션 짝, 사후 선택 불가):

* v3-mix − 원음: SI-SDRi +0.24 dB (CI −0.45..+1.03), cpWER +8.5 %p, DER −32.7 %p.
* v3-real − 원음: SI-SDRi +1.61 dB (CI +0.71..+2.60), cpWER −9.0 %p (CI −14.8..−3.5, 상대 약 −11 %), DER −45.6 %p.
* v3-real − v3-mix: SI-SDRi +1.37 dB (CI +0.81..+1.97), cpWER −17.5 %p.

**해석**

* 새 장소에서는 AMI에서 얻은 이득이 대부분 사라졌다. blind3(AMI TNO)에서 기준 대비 +3.36 dB였던 v3-mix는 blind4에서 +0.93 dB다. 원음 대비로는 0과 구분되지 않는다(+0.24 dB, CI가 0을 포함).
* 원인 후보는 둘이다. (1) 방·화자·장비가 학습과 다르다. (2) 배열 형상을 가정했다(ch0 가운데, 4.25 cm 원, 짝 ch1). 학습한 AMI 짝 간격은 7.65 cm다. 이번 시험으로는 둘을 나눌 수 없다.
* DER은 모든 시스템에서 크게 줄었다. 분리기가 화자 구간을 나누는 데는 일관되게 도움이 된다.
* cpWER은 후보가 원음보다 나쁘다. 한 스트림에 다른 화자가 충분히 남아 ASR이 섞인 소리보다 못하다는 blind3의 관찰이 새 장소에서도 이어진다.
* v3-real이 모든 지표에서 v3-mix보다 낫다. dev cpWER에서도 그랬다(§17.1). 그러나 후보는 blind3 전에 dev SI-SDRi로 고정했다. 이 결과를 보고 v3-real로 바꾸면 시험 자료로 고르는 것이 되므로 바꾸지 않는다. v3-real도 REQ-402 cpWER 기준(−15 %)에는 못 미친다.

**상태와 남은 일**

* REQ-303은 미달이다(§18 사전 등록대로 새 장소 결과로 갱신). REQ-305는 보류, REQ-402는 미달이다.
* 지금까지 연 시험 세트(TS3003, blind2, blind3, blind4)는 다시 열지 않는다. NOTSOFAR eval 세트의 나머지 회의는 열지 않았다. 새 장소 시험으로 쓰려면 blind4와 방이 겹치지 않는지 먼저 확인해야 한다.
* 다음 정식 판정에는 새 개발 주기와 새로 열지 않은 시험 세트가 필요하다. 개발에 쓸 수 있는 방향은 다음과 같다. 개발 자료로만 고르고 결과는 새 시험 세트에서 확인한다.
  * 실측 학습 비율을 높이거나(v3-real 방향), NOTSOFAR train/dev 세트로 배열·방을 넓힌다.
  * 배열 형상을 장치 정보로 확인하거나 형상에 덜 민감한 입력을 쓴다.
  * 스트림 간 누설을 줄이는 목표(예: ASR 기반 선택 지표)를 dev에서 정한다.

## 19. v4: NOTSOFAR 실측 학습과 새 장소 blind5 판정 규약 (2026-11-24, 내려받기·학습 전에 고정)

blind4에서 REQ-303·REQ-402는 미달, REQ-305는 보류였다(§18.2). 사용자가 2026-11-24 v4 개발 주기와 NOTSOFAR-1 자료 내려받기(약 15.7 GB 이내)를 승인했다. 아래 내용은 오디오를 받기 전에 정했다. 결과를 본 뒤에는 바꾸지 않는다. 기계가 읽는 사본은 `reports/experiments/blind5_notsofar/preregistration.json`이다.

* **분리 점검(메타데이터만 사용)**
  * NOTSOFAR dev1은 train과 방 1개(ROOM_10007)와 화자 12명 중 10명을 공유한다. NOTSOFAR 전체 화자는 35명이므로 별칭은 실제 사람이다. 그래서 dev1은 판정에 쓰지 않고 선택에만 쓴다.
  * 열지 않은 eval 회의 79개는 방·화자 모두 train·dev1과 겹치지 않는다. 그중 4개 방(ROOM_10027/31/36/38, 52회의)은 blind4를 포함해 어디에도 쓰지 않았다. 이 52회의를 blind5로 한다.
  * blind5 화자 12명 중 6명은 blind4에 나왔다(평가만, 학습 없음). 한계로 적는다.
* **학습 자료**: NOTSOFAR train 71회의(ROOM_10007의 1회의 MTG_30933 제외, dev1 방과 분리), `mc_plaza_0`의 ch0·ch1·ch4. 장면은 AMI와 같은 방법, 회의당 최대 40장면, 시드 `[410, 회의 번호]`.
* **변형**(설정은 v3과 같음: 30,000 스텝, 배치 16, 시드 0, 기본 증강, AGC는 v2 값)
  * v4-nsf: NOTSOFAR train 100 %.
  * v4-real: NOTSOFAR train 50 % + AMI ES/IS train(v3 실측 장면) 50 %.
* **선택(dev1만 사용)**: 후보는 v4-nsf, v4-real, v3-real, v3-mix다. dev1 36회의(회의당 최대 40장면, 시드 `[420, 회의 번호]`)에서 세션 평균 cpWER이 가장 낮은 후보를 고른다. 단, dev1 세션 평균 SI-SDRi가 v2 base보다 높아야 한다. 같으면 SI-SDRi가 높은 쪽이다. cpWER을 고르는 지표로 쓰는 것은 미충족 요구가 REQ-305·402이고, 진단(§17)에서 시간순 결합 WER이 분리를 반영하지 못했기 때문이다.
* **blind5 판정**: 기준 v2 base, 비교 원음, 참고 v3-mix. Whisper small.en GPU.
  * 장면은 회의당 최대 40개, 시드 `[500, 회의 번호]`이다. 장면 10개 이상인 회의만 세션으로 세고, 20세션 미만이면 보류한다.
  * REQ-303: 후보 − v2 base SI-SDRi 세션 평균 ≥ +1.5 dB.
  * REQ-305·402·405: 승인된 `configs/decision_rules.yaml`을 `gate.decide`로 그대로 적용한다.
  * blind5 결과로 REQ-303·305·402 상태를 정한다(통과·미달 모두).
* **열기**: 선택한 후보의 해시를 고정하고 한 번만 연다. 접근 기록은 `reports/experiments/blind5_notsofar/access_log.json`이다.

### 19.1 v4 결과와 blind5 판정 (2026-11-24, 한 번 열어 판정)

* **학습**(GPU, 30,000 스텝, 각 약 1.85시간): v4-nsf는 NOTSOFAR train 1,094장면, v4-real은 NOTSOFAR 1,094장면 + AMI 1,280장면(반반)이다. 둘 다 오류 없이 끝났다.
* **dev1 선택**(15회의, 473장면, 세션 평균, `real_v4/dev1_select.json`)

  | 후보 | cpWER | SI-SDRi − v2 base | 자격 |
  | --- | --- | --- | --- |
  | v4-real | 0.600 | +5.26 dB (CI +4.31~+6.15) | 예 |
  | v3-real | 0.698 | +1.87 dB | 예 |
  | v4-nsf | 0.782 | +1.83 dB | 예 |
  | v3-mix | 0.833 | +1.85 dB | 예 |

  규칙대로 v4-real(해시 `5554f37d609e…`)을 골랐다. dev1은 v4 train과 화자 12명 중 10명을 공유하므로(방은 MTG_30933 제외로 겹치지 않음) 이 수치는 판정에 쓰지 않는다.
* **blind5 열기**: 고정 해시를 확인하고 한 번 열었다. 52회의 중 장면 10개 이상인 26세션, 846장면, 시스템 4개(원음, v4-real, v2 base, v3-mix), Whisper small.en GPU. 접근 기록은 1건이다.
* **판정**(세션 평균, `gate.decide`, 승인 규칙 그대로)

  | 요구 | 결과 | 판정 |
  | --- | --- | --- |
  | REQ-303 (기준 대비 SI-SDRi ≥ +1.5 dB) | +4.33 dB (CI +3.59~+5.09) | **통과** |
  | REQ-305 (기준 대비 cpWER ≤ −3.0 %p, CI 상한 < 0) | 0.866 → 0.642, −22.4 %p (CI −26.1~−18.7) | **통과** |
  | REQ-402 cpWER (원음 대비 ≤ −15 %) | 0.837 → 0.642, −23.3 % | 통과 |
  | REQ-402 DER (원음 대비 ≤ −5 %p) | 0.890 → 0.355, −53.5 %p | 통과 |
  | REQ-402 종합 | | **통과** |
  | REQ-405 회귀 (WER 악화 < 0.5 %p) | −16.5 %p | 통과 |

* **참고**: v4-real은 v3-mix보다 SI-SDRi +2.70 dB, cpWER −17.9 %p 낫다. v3-mix의 결과는 blind4와 blind5에서 다르다. 원음 대비 cpWER은 blind4 +8.5 %p(CI +0.5~+16.8), blind5 −1.5 %p(CI −5.6~+2.7)이고, SI-SDRi는 +0.24 dB와 +1.77 dB다. v2 base 대비 SI-SDRi도 +0.93 dB와 +1.63 dB다. 즉 같은 모델에 blind5가 더 쉬웠고, 그 점 추정만 보면 v3-mix도 blind5에서는 REQ-303의 +1.5 dB를 넘는다. 따라서 blind4 미달에서 blind5 통과로 바뀐 것을 학습 자료만의 효과로 볼 수 없다. 같은 blind5 안의 짝 비교(v4-real − v3-mix: SI-SDRi +2.70 dB, cpWER −17.9 %p)는 같은 장면에서 잰 모델 차이다(크기는 세트에 따라 다를 수 있다). 이 차이의 원인(NOTSOFAR 자료, AMI 자료, 합성 자료 제외)은 나누어 시험하지 않았고, dev1에서 NOTSOFAR만 쓴 v4-nsf는 v3-real보다 cpWER이 나빴다. v4-real은 blind4에서 평가하지 않았다(다시 열지 않는다).
* **한계**
  * 같은 말뭉치·같은 장비(`mc_plaza_0`)다. 새 방·새 화자로의 일반화이고, 새 장비로의 일반화는 아니다.
  * blind5 화자 12명 중 6명은 blind4에 나왔다(평가만, 학습 없음).
  * 배열 형상(ch0 가운데, 4.25 cm 원)은 가정이다.
  * 시간순 결합 WER은 여전히 원음보다 높다(0.655 대 0.410). §17에서 이 지표는 정답 분리 신호도 원음보다 나쁘게 매긴다고 확인했으므로 수용 지표가 아니다.
* **결론**: 사전 등록 규약대로 REQ-303·305·402를 충족으로 바꾼다. blind5는 사용했으므로 다시 열지 않는다(TS3003, blind2, blind3, blind4, blind5).
