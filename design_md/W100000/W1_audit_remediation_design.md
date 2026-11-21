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

| 태스크 | 필요한 정답 | 최소 수량(제안, 확정 필요) | 정답이 없을 때 |
| --- | --- | --- | --- |
| 분리(SI-SDRi) | 근접 마이크 참조 파형 | 세션 20개, 검수 10% | 비지도/혼합 일관성 손실만 허용, SI-SDRi 보고 제외 |
| ASR(WER) | 전사 | 2시간 | 해당 지표 분모에서 제외하고 유효 분모 표시 |
| 화자 분할(DER) | 화자 타임라인 | 2시간 | 동일 |
| 위치(각도 오차) | 위치 정답과 좌표계 | 출시 범위일 때만 | 지표 미보고 |

### 6.2 성공 판정 (F-06)

같은 세션에서 **원음 / 고정 기준 분리 모델 / 후보 모델**을 비교한다.

| 지표 | 비교 기준 | 합격 조건(제안) | 경계·동률 |
| --- | --- | --- | --- |
| WER | 고정 기준 모델 | 절대 −3.0 %p 이상 개선 (REQ-305) | 정확히 −3.0 %p는 합격. 기준 WER 0이면 후보도 0이어야 합격 |
| WER | 원음 | 상대 −15 % 이상 (REQ-402) | 기준 WER 0이면 상대값 대신 절대 +0.5 %p 이하 악화로 판정 |
| 주요 조건별 회귀 | 고정 기준 모델 | 어떤 조건도 WER 절대 +0.5 %p 초과 악화 금지 (REQ-405 "1% 미만"을 %p로 고정) | 0.5 %p 초과는 실패 |
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
| §6 설계 결정 | 제안값. 제품 책임자 확인 필요 | 이 문서 |

시험: 기존 440개(감사 시점 17개 실패)와 신규 66개, 총 506개 통과 (Python 3.14, numpy 2.5, scipy 1.18).

남은 관찰: Zoom 시나리오 생성기는 의자끼리, 의자와 벽이 겹치는 배치를 만든다(씬 매니페스트 `plausibility.warnings`에 기록됨). 감사 범위 밖이므로 별도 과제로 남긴다.

## 9. 남는 위험과 확인 필요

* 실측 자료의 접근 범위, 주석 수량, §6의 제안 임계값은 제품 책임자의 확인이 필요하다.
* `static_v1` 밖의 이동 렌더(`w134`)는 정적 입력 동등성 시험이 생길 때까지 정상 경로에 연결하지 않는다.
* GUI는 이 환경에서 Gradio를 불러올 수 없어(Windows 애플리케이션 제어 정책이 `pydantic_core` DLL을 차단) 콜백 로직을 순수 모듈로 옮겨 시험한다. 실제 UI 클릭 확인은 남아 있다.
