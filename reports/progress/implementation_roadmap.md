# 구현 개발 로드맵과 진척 현황

정본 위치. 단계가 끝날 때마다 이 파일의 체크 상태와 진척 막대를 갱신하고, 같은 내용을 `reports/progress/YYMMDD_<단계>_progress.md`로 남긴다([PROJECT_RULES.md](../../PROJECT_RULES.md) §진척 보고).

* 기준: [WBS 개요 §5](../../design_md/WBS_Overview_3D_Audio_Separation.md), [감사 보고서](../../review_docs/261120_1716_fresh_eyes_audit.md)의 권고 순서, [W1 감사 개선 설계](../../design_md/W100000/W1_audit_remediation_design.md)
* 우선순위 원칙: 첫 종단 간 검증(16 kHz, 정적 회의실, 두 화자, 고정 기준 마이크, 분리+ASR)을 먼저 통과시킨 뒤, 측정한 실패를 근거로 이동·배열·기기·규모 확장 순서를 정한다.
* 진척률 계산: 단계마다 검증 가능한 항목 수로 센다(항목 가중치 동일). 항목은 **코드와 시험, 또는 승인된 결정 문서**가 있을 때만 완료로 표시한다. 설계 제안만 있고 확인되지 않은 항목은 미완료다.
* 최종 갱신: 2026-11-24, v4 학습과 새 장소 blind5(NOTSOFAR-1 eval 26세션) 정식 판정 반영 — 57/57 (커밋 `fd867f9` 이후 작업 트리)

## 단계 목록 (우선순위 순)

| 순위 | 단계 | WBS | 감사 근거 | 완료/전체 |
| --- | --- | --- | --- | --- |
| 1 | W1 정상 경로 복구와 데이터 계약 | W1 | F-01, F-02 | 7/7 |
| 2 | W1 운영 일관성과 지원 범위 | W1 | F-07, F-08, F-09, F-11 | 8/8 |
| 3 | 실측 자료 확보와 평가 규칙 확정 | W3·W4 | F-03, F-04, F-06 | 6/6 |
| 4 | 소규모 정적 데이터셋 발행 (W2 최소판) | W2 | F-02, F-04, F-11 | 7/7 |
| 5 | 기준 학습과 실측 dev 평가 (첫 종단 간 검증) | W3·W4 | F-05, F-06 | 8/8 |
| 6 | 동적 장면·센서 확장 (WBS Phase 2) | W1·W2 | F-09 | 6/6 |
| 7 | 도메인 격차 축소 (WBS Phase 3) | W3 | F-10 | 7/7 |
| 8 | 후속 태스크 입증과 배포 판정 (WBS Phase 4) | W4 | F-05, F-06, F-12 | 8/8 |

## 단계별 항목

### 1. W1 정상 경로 복구와 데이터 계약 — 완료

- [x] RIR 호출 인자 오류 복구 (`src_pos`) — `propagation.py`
- [x] 설정 ID·좌표·재질이 렌더러까지 전달 (N-01, N-02, N-06) — `test_config_positions_are_rendered`, `test_material_changes_rir`
- [x] RIR 신호 정상화: 잔향 크기·NaN, ISM 좌표 (N-07) — `test_rir_finite_short_rt60`, `test_image_sources_never_precede_direct_path`
- [x] IEEE float32 WAV와 왕복 검증 — `test_wav_float32_roundtrip`
- [x] 혼합음·참조·잡음 공통 시간축 계약, 매니페스트 v2, 라벨 — `test_e2e_2x2_scene`
- [x] QC 검사, 원자적 확정, 격리 — `test_qc_failure_quarantines`
- [x] 감사 시점 실패 시험 17건 복구 — 전체 506 통과

### 2. W1 운영 일관성과 지원 범위 — 완료

- [x] GUI·API 공통 설정 해석기, Zoom 왕복 서명 유지, YAML — `test_zoom_roundtrip_signature`, `test_app_callbacks.py`
- [x] 작업 지문, 체크포인트 v2, 검증 후 재개 — `test_batch_resume.py`
- [x] 채널별 장치 파라미터, 배열 위치·시계 오차 — `test_per_channel_gain_applied`, `test_array_errors_change_geometry`
- [x] `static_v1` 지원 범위 검사 — `test_moving_source_rejected`
- [x] 실제 브라우저에서 GUI 6개 탭 조작 확인 — 2026-11-22 Gradio 6.32가 로드되어(Smart App Control 해제 후) 실제 서버를 띄워 확인했다. 브라우저 조작: 장면 1개 생성(요약·오디오 표시), 배치 2/2, Zoom 미리보기, 설정 내보내기. 업로드가 필요한 세 기능은 같은 서버 API(`gradio_client`)로 확인: 결과 보기, 설정 가져오기(서명 유지), 파일 실행 2/2. Zoom 참가자 수 슬라이더에 "저장은 n±2에서 뽑는다" 안내를 추가했다
- [x] TDOA 시험 분리: 직접파 지연차 ±1 샘플, 평면 내 분수 지연 TDOA < 1° (REQ-W03), 단일 쌍 대칭 모호성 — `test_tdoa.py`
- [x] 처리량 측정: 8 워커 1,578 RIR/s(REQ-W04 ≥ 1,000), 약 13,000 씬/h(REQ-W10 ≥ 1,000) — `scripts/bench_throughput.py`, `reports/perf/`
- [x] 파일럿: QC 통과 오디오 약 47 h/h, 씬당 16.1 MB(full)·10.0 MB(training), 실패 0% — `reports/perf/pilot_report.md` (F-11)

### 3. 실측 자료 확보와 평가 규칙 확정 — 완료

- [x] 실측 세션 등록부 스키마와 태스크별 정답 요구 설계 (설계 §6.1)
- [x] 등록부 검증, 세션 단위 분할(방·화자 연결 유지), blind 접근 차단, 지표별 유효 분모 집계 도구 — `datatools/real_sessions.py`, `test_real_sessions.py` (항목 분해: 도구 구현을 실제 분할 확정과 분리)
- [x] 사용 가능한 실측 녹음 확보와 사용 범위·동의 확인: AMI 회의 코퍼스 6회의(Array1 8채널+헤드셋 4, CC BY 4.0, 참가자 동의는 코퍼스 공개 조건으로 확인 — 자체 재확인 아님) — `datatools/ami.py`, `configs/real_sessions_ami.csv`
- [x] 세션 단위 dev / blind_test 분할 확정: 방·화자 연결 그룹 단위로 dev 4세션(Edinburgh·IDIAP) / blind_test 2세션(TNO). blind_test는 `BlindTestGuard`로 고정 후보만 접근 — `configs/real_sessions_ami.csv`
- [x] 판정 규칙 임계값 승인 — 2026-11-23 제품 책임자 승인. `configs/decision_rules.yaml`은 `status: approved`이고, 회귀 게이트 판정은 이제 권고가 아니라 출시를 막는다 — `test_stage8.py::test_gate_blocks_half_percent_wer_regression`
- [x] 정답 결측 시 허용 학습 모드와 지표별 유효 분모 규칙 승인 — 2026-11-23 제품 책임자 승인(설계 §6.1). 유효 분모 집계는 `datatools/real_sessions.py`에 구현되어 있다

### 4. 소규모 정적 데이터셋 발행 (W2 최소판) — 완료

- [x] 음원 입력 계약: `signal_path`, `onset_s`, `level_dbfs`, 리샘플 — `test_dry_signal_file_and_onset`
- [x] 합성 전 그룹 분할과 누수 검사 도구, 음성·잡음·방 풀 분리(REQ-206) — `test_datatools.py`, `test_req206_asset_pools_have_no_leakage`
- [x] 매니페스트 기반 데이터 로더 — `datatools/loader.py`
- [x] 시나리오 계획기: 1만 건 7.9 s·중복 0·제약 위반 0(REQ-201), 음원 역할·정확한 목표 SNR ±1 dB(REQ-202), VAD 기반 중첩 단계별 누적 오차 < 5 %(REQ-203), 1 ms VAD 라벨 F1 > 0.999(REQ-204) — `datagen/planner.py`, `test_datagen.py`
- [x] 데이터셋 QC 게이트(클리핑·무음·SNR)와 불변 버전 릴리스(샤드·인덱스·분할 목록·체크섬) (REQ-205) — `datagen/publish.py`, `scripts/make_dataset.py`
- [x] 데이터셋 QC 집계 리포트와 희귀 조건 보충 생성 — `qc_report.json`, `supplement_plans`
- [x] 실제 음성·잡음 코퍼스 등록: LibriSpeech dev-clean 2,703 / test-clean 2,620 발화(전사 포함, CC BY 4.0), DEMAND 17환경 170구간(CC BY-SA 3.0). 화자·환경 단위 분할, 실음성 장면 1,200 × 3세트 렌더 — `datagen/external.py`, `scripts/import_external.py`

### 5. 기준 학습과 실측 dev 평가 (첫 종단 간 검증) — 완료

- [x] 평가기 코어: SI-SDR/SI-SDRi(혼합음 기준), WER, 텍스트 정규화 — `test_si_sdr_golden`, `test_wer_golden`
- [x] 화자 순열 매칭과 누락·추가 화자 처리 — `test_permutation_*`
- [x] 기준 분리 학습 파이프라인: 고정 기준(SRP-PHAT + 지연합), 학습 후보(능선 회귀 비율 마스크), 릴리스 지문 검증, 결정적 체크포인트, 실험 매니페스트 — `src/training/`, `test_training_pipeline.py`
- [x] ASR 연동 인터페이스와 다중 스트림 시간순 결합 평가(외부 명령 백엔드 포함) — `evaluation/asr.py`, `test_evaluation.py`
- [x] 실제 ASR 모델로 WER 측정: Whisper small.en(MIT). LibriSpeech test-clean 2화자 12 s 장면에서 혼합음 WER 0.60, 분리 후 0.76–0.98(악화). 분리 출력에 다른 화자가 새어 두 스트림이 같은 단어를 반복(삽입)함을 표본 확인 — `evaluation/asr.py`, `reports/experiments/real_v1/eval_asr_librispeech/`
- [x] DER(중첩 채점, 칼라, 헝가리안 매핑)과 스트림 기반 화자 분할 — `evaluation/diarization.py`, `test_evaluation.py`
- [x] 원음 / 고정 기준 / 후보 비교 리포트(쌍 비교 부트스트랩 CI), 합성 홀드아웃 30씬 실행 — `evaluation/compare.py`, `reports/experiments/e2e_synthetic_v1/`
- [x] 실측 dev에서 같은 비교 실행: AMI dev 4세션 160장면. SI-SDRi base 1.18 / robust 1.61 / cal 1.81 dB, DER 0.74 → 0.43, WER 0.46 → 0.82(악화). 사전 규칙대로 cal을 고정(sha256 `b4cf6161…`)한 뒤 blind_test 80장면: cal −1.84 dB, base +0.16 dB — `scripts/run_real_data_experiments.py`, `reports/experiments/real_v1/ami_eval.json`

### 6. 동적 장면·센서 확장 — 완료

- [x] 이동 렌더(`dynamic_v1`)를 정상 경로에 연결, 정적 입력 동등성 −80 dB 미만 — `test_dynamic_static_equivalence`
- [x] 구간 경계 불연속 −60 dB 미만(1 m/s, 20 ms 틱), 틱별 지연·DOA 추적 라벨 (REQ-W06) — `test_dynamic_moving_source_no_clicks_and_traces`
- [x] 잡음·과도 이벤트 주입과 중첩 난이도 단계 (REQ-203) — `test_events_injected_as_interference`, `test_req203_*`
- [x] 대역별 잔향: 옥타브 대역 이미지 이득·RT60, 인과 필터, 직접파 광대역 — `test_band_reverb_frequency_dependent_and_causal`
- [x] 경로별 지향성과 바이노럴(합성 HRTF): ILD > 5 dB @2 kHz, 정면 ITD < 50 µs, 무작위 머리 방향 측방각 RMS < 5° (REQ-W05) — `test_stage6_rendering.py`
- [x] 측정 HRTF 데이터베이스와 피험자 무작위화: HUTUBS 96명(SOFA, CC BY 4.0). 경로별 최근접 방향 HRIR, 정면 도달 중심 정렬(ITD·ILD 보존), 계획기의 `binaural` 배열에서 장면마다 피험자 추출 — `simulator/hrtf_db.py`, `test_external_data.py`

### 7. 도메인 격차 축소 — 완료

- [x] 합성·실측 혼합 커리큘럼 샘플러와 프리페치: 1만 스텝 비율 오차 < 5 %, 소비자 대기 < 5 % (REQ-301) — `training/curriculum.py`, `test_domain_gap.py`
- [x] 시뮬레이터 보정: 블라인드 RT60(0.3/0.5/0.8 s → 0.305/0.468/0.871 s), 보정 프로필의 W2 계획기 전달, 역 Sabine 흡음, 명시 흡음 재질 (REQ-302) — `training/calibration.py`
- [x] 기기·환경 강건성 증강(선형, 위상차 보존)과 미지 방·배열 3종 평가 실험 (REQ-303) — `training/augment.py`, `reports/experiments/domain_gap_v1/`
- [x] 도메인 적응(CORAL, 라벨 없는 대상 데이터) 통합과 dev 쌍 비교 기반 채택; BCE는 진단 (REQ-304) — `training/adaptation.py`
- [x] REQ-302 분포 일치 KL ≤ 0.1: 대리 실측 300세션에 폐루프 보정 2회 반복으로 KL 0.211→0.151→0.059, RT60 0.5 s 수용 중앙값 0.459 s(±0.075 이내). 실측 세션 적용은 W3 실측 자료 항목에 남음 — `reports/experiments/calibration_v1/`
- [x] REQ-303 미지 영역 +1.5 dB — **충족(새 장소 blind5로 판정, 2026-11-24)**: dev1로만 고른 v4-real(해시 `5554f37d…`, NOTSOFAR train + AMI 반반)을 NOTSOFAR-1 eval 26세션 846장면(학습·선택·blind4에 쓰지 않은 4개 방)에서 한 번 열었다. v2 base 대비 +4.33 dB(세션 CI +3.59~+5.09), 원음 대비 +4.48 dB. 같은 장비·말뭉치의 새 방·새 화자 일반화이며 배열 형상은 가정이다. 앞선 blind4 v3-mix는 +0.93 dB로 미달이었다 — `reports/experiments/blind5_notsofar/result.json`, 설계 §19·§19.1
- [x] 실측 자료로 보정·적응 효과 검증(효과 없음 확인): 보정 — AMI dev RT60 분포로 보정한 cal은 dev에서 robust 대비 +0.20 dB(CI −0.15~0.56, 유의하지 않음), 다른 장소인 blind_test에서는 base보다 −2.00 dB. 적응 — 신경 분리기 입력 특징에 대역별 CORAL을 연결하고 라벨 없는 dev-a 혼합음 80장면으로 맞춘 뒤 dev-b 80장면에서 측정: SI-SDRi base −1.34 / robust −0.71 / cal −0.79 dB(사전 규칙 CI 하한 > 0 불충족, 채택 안 함), DER은 0.01–0.02 개선. v2 모델에 같은 규칙을 적용하니 robust+CORAL이 +0.74 dB(CI 0.08~1.36)로 채택 조건을 충족했다. 다만 3개 모델 다중 비교를 보정하면 CI가 −0.05~1.49 dB로 0을 포함한다. base −0.85, cal +0.49(CI −0.13~1.15)는 채택하지 않음 — `training/neural.py::fit_feature_coral`, `reports/experiments/real_v1/ami_adapt.json`, `reports/experiments/real_v2/ami_adapt.json`

### 8. 후속 태스크 입증과 배포 판정 — 완료

- [x] 버전 고정 벤치마크: 선언 해시 검증, 샤드에서 자체 복원, 결정적 순서, 서버 3곳 텐서 해시 일치, 변조·누락 검출 (REQ-403) — `evaluation/benchmark.py`, `test_stage8.py`
- [x] 위치·추적 지표와 요구사항 초안(REQ-406, W414): 방위 오차, 재현율·정밀도, ID 전환, 단절; 이동 음원 추적 재현율 > 0.8 — `evaluation/localization.py`
- [x] 요인 제거·조합 대시보드(영향 %, 상호작용, 지표 간 상관, PDF) (REQ-404) — `evaluation/ablation.py`, `reports/experiments/ablation_v1/ablation.pdf`
- [x] 회귀 게이트와 blind 판정: 0.5 %p WER 회귀 차단, 표본 부족 시 보류, 규칙 `proposed`면 권고 표시, CI 종료 코드 (REQ-405) — `evaluation/gate.py`, `scripts/release_gate.py`, `reports/gate/`
- [x] 요구사항–시험–증거 추적표: 32개 요구사항, `--strict` 통과 (F-12) — `configs/traceability.yaml`, `scripts/trace_check.py`, `reports/traceability.md`
- [x] REQ-401 합성 벤치마크 SI-SDRi ≥ 8 dB: 1 h(360장면) 잠금 벤치마크에서 BLSTM PIT 신경 분리기 8.28 dB(CI 7.77–8.77), 평가 93 s — `training/neural.py`, `reports/experiments/req401_neural/`
- [x] REQ-305 후속 태스크로 본 격차 축소 — **충족(blind5 정식 판정, 2026-11-24)**: 승인된 cpWER 규칙으로 v4-real vs v2 base 0.642 vs 0.866, −22.4 %p(세션 CI −26.1~−18.7). 앞선 blind4 v3-mix는 −5.15 %p로 보류였다 — `reports/experiments/blind5_notsofar/result.json`, 설계 §17·§19.1
- [x] REQ-402 ASR·화자 구분 무결성 — **충족(blind5 정식 판정, 2026-11-24)**: cpWER 원음 0.837 → v4-real 0.642(상대 −23.3 %, 목표 ≤ −15 %), DER 0.890 → 0.355(−53.5 %p). 두 조건 모두 통과. 시간순 결합 WER은 여전히 원음보다 높지만(0.655 대 0.410) 수용 지표가 아니다(§17) — `reports/experiments/blind5_notsofar/result.json`, 설계 §19.1
