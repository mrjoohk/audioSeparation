# PROJECT_RULES.md — audioSeparation (3D Audio Separation)

## 목적과 환경

- 대상·목적: 실내 음향을 합성해 음성 분리용 학습 데이터를 만들고, 실측 데이터에서 분리·ASR·화자 분할·위치 추정 성능 향상을 입증한다.
- 주요 입력·정본:
  - 전체 설계: [design_md/WBS_Overview_3D_Audio_Separation.md](design_md/WBS_Overview_3D_Audio_Separation.md), `design_md/W100000`–`W400000`
  - 감사와 개선 설계: [review_docs/261120_1716_fresh_eyes_audit.md](review_docs/261120_1716_fresh_eyes_audit.md), [design_md/W100000/W1_audit_remediation_design.md](design_md/W100000/W1_audit_remediation_design.md)
  - 구현 로드맵·진척 정본: [reports/progress/implementation_roadmap.md](reports/progress/implementation_roadmap.md)
  - 코드: `src/simulator`(W1), `src/datagen`(W2), `src/training`(W3), `src/evaluation`(W4), `src/datatools`(공용 인계·분할·지표), `app.py`(Gradio GUI)
  - 설정 정본: `configs/scenario_prior.yaml`(W2 사전 분포), `configs/decision_rules.yaml`(판정 규칙, 현재 `proposed`), `configs/traceability.yaml`(요구사항–시험–증거)
  - 요구사항 추적표: `scripts/trace_check.py --strict`로 검사하고 `reports/traceability.md`를 생성한다. 요구사항이나 시험을 바꾸면 함께 갱신한다.
- 실행 환경·검사:
  - 프로젝트 `.venv`(Python 3.14, numpy, scipy, pyyaml, pytest). 생성: `py -3.14 -m venv .venv` 후 `pip install numpy scipy matplotlib pyyaml pytest plotly`
  - 필수 검사: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` 전체 통과
  - GUI 로직은 `tests/unit/test_app_callbacks.py`(gradio 스텁)로 검사한다. 실제 UI는 `.claude/launch.json`의 `gui` 구성(`app.py`, 포트 7860)으로 띄워 확인한다. 이 PC에서 Smart App Control이 켜져 있으면 `pydantic_core`·`torch` DLL이 막힌다(2026-11-22 해제 후 Gradio·CUDA 동작 확인).
  - CUDA 학습(torch 2.15+cu132, cuDNN 9.26)은 드롭아웃 다층 LSTM을 학습한 프로세스가 종료 처리 중 0xC0000409로 끝난다. `run_real_data_experiments.py`는 CUDA 학습 단계 뒤 종료 처리를 건너뛴다.
  - 이 PC의 C 드라이브 공간이 부족하여 `data/external/`은 `E:\audioSeperation\data\external`로 옮기고 정션으로 연결했다(2026-11-22). 큰 내려받기·생성 자료는 E 드라이브에 둔다.
- 프로젝트 제약:
  - 렌더 지원 범위는 `static_v1`이다. 지원 밖 입력은 거부하고, 근사는 매니페스트 `render.approximations`에 남긴다.
  - 출력 계약(매니페스트 2.0.0, float32 WAV, 상대 경로)을 바꿀 때는 개선 설계 §3과 [USER_MANUAL.md](USER_MANUAL.md) §7을 함께 갱신한다.
  - 기존 시험을 수정할 때는 근거를 개선 설계 §8에 기록한다.

## 작업 운영

- workflow_mode: lightweight
- 태스크 분해: 작은 일은 메인 직접, 독립적으로 끝낼 수 있는 일은 명확한 입력·출력·수정 범위로 위임.
- 병렬 작업: 같은 파일의 writer는 하나. 로드맵 정본은 메인이 단일 소유자로 갱신한다.
- 출력 형식·위치: 설계는 `design_md/`, 검토는 `review_docs/`, 진척 보고는 `reports/progress/`.
- 필수 검사·승인 경계: 전체 pytest 통과 후 완료로 보고한다. 커밋·푸시는 사용자 요청이 있을 때만 하며, 기본 브랜치에서는 브랜치를 먼저 만든다.

## 진척 보고 (필수, 2026-11-21 사용자 요청)

1. 구현 개발 단계는 [reports/progress/implementation_roadmap.md](reports/progress/implementation_roadmap.md)에 **우선순위 순**으로 유지한다. 단계를 추가·재배열하면 근거(설계 문서, 감사 항목, 측정 결과)를 함께 적는다.
2. **단계 하나가 끝날 때마다** 진척 보고서를 작성한다.
   - 대화에 바로 보고하고, 같은 내용을 `reports/progress/YYMMDD_stage<N>_progress.md`로 저장한다.
   - 로드맵 정본의 체크 상태, 단계별 완료/전체 수, 최종 갱신일·커밋을 함께 갱신한다.
3. 보고서 형식:
   - 전체 진척과 단계별 진척을 **텍스트 프로그레스바**로 표시한다. 형식: `[████░░░░] NN%  완료/전체  상태`, 막대 폭 20칸, 칸 수 = round(진척률 × 20).
   - 완료한 단계와 그 근거(시험·파일·커밋), 다음 단계의 남은 항목, 막힌 항목과 이유를 적는다.
4. 진척률은 단계별 검증 가능한 항목 수로 계산한다(가중치 동일). 코드와 시험, 또는 승인된 결정 문서가 있을 때만 완료로 센다. 설계 제안만 있는 항목은 미완료다.

## 현재 미해결 사항

- 실측 회의 녹음의 확보 범위, 주석 수량, 판정 임계값(개선 설계 §6)은 제품 책임자 확인이 필요하다.
- Zoom 시나리오 생성기가 의자끼리, 의자와 벽이 겹치는 배치를 만든다(씬 매니페스트 `plausibility.warnings`에 기록).
- 이 PC에는 git 사용자 정보가 설정되어 있지 않다.
