# 프로젝트 시작 팩

기본은 가벼운 작업 흐름이다. 사용자 요청을 완료하는 데 필요한 지침만 읽고, 추적·감사 체계는 해당 프로젝트에서 필요할 때 선택한다.

## 시작

1. 작업공간에는 ai_skills 저장소 한 벌을 두고 PC마다 아래 공용 설치를 한 번 실행한다. 새 프로젝트에는 AGENTS.md와 CLAUDE.md를 복사한다. 기존 프로젝트에는 필요한 지침을 병합하며 덮어쓰지 않는다. 공통 규칙은 작업공간의 GLOBAL_RULES.md를 읽으며, 독립 배포라면 이 팩의 GLOBAL_RULES.md도 복사한다.
2. 프로젝트 사실을 지속적으로 공유할 필요가 있으면 PROJECT_RULES.template.md를 채워 PROJECT_RULES.md로 저장한다. 모든 항목을 채우기 위한 질문부터 시작하지 않는다.
3. 작은 작업은 메인이 직접 수행한다. 독립 태스크가 유용하면 서브에이전트를 사용하고, 메인이 공유 파일·통합·검증을 책임진다.
4. 버전 관리·검사 명령은 프로젝트 환경에 맞게 사용한다. 작업을 시작하기 위해 자동으로 git init이나 새 채팅을 만들지 않는다.

## 공용 스킬 사용

기본 시작 팩에는 스킬 사본을 넣지 않는다. 공용 설치는 사용자 `.agents/skills/`(Codex)와 `.claude/skills/`(Claude Code)의 스킬별 링크를 정본에 연결한다. Windows에서는 심볼릭 링크 권한이 없을 때 정션을 사용한다. 라이브러리 루트에서 실행한다.

```powershell
python -B scripts/setup_shared_skills.py --dry-run
python -B scripts/setup_shared_skills.py
python -B scripts/setup_shared_skills.py --check
```

이 설정기는 작업공간 GLOBAL_RULES.md와 사용자 전역 지침에 표시된 공용 블록만 병합한다. 기존 지침·스킬 사본·다른 링크는 덮어쓰지 않는다. 기존 스킬 폴더가 충돌하면 아무것도 변경하지 않고 보고한다. 경로는 AI_SKILLS_HOME 또는 상위 폴더의 ai_skills/skills/pipelines.json으로 정하며, PC마다 드라이브·작업공간 이름이 달라도 된다. 프로젝트 밖 worktree에는 AI_SKILLS_HOME을 설정한다.

공용 스크립트는 실제 프로젝트에서 실행한다. 문서·SDD 도구의 --project-root 또는 AI_PROJECT_ROOT로 프로젝트를 명시할 수 있다. 스킬 위치는 산출물 저장 위치가 아니다. 도구가 사용자 설정을 읽을 수 있는 새 세션에서 공용 스킬을 확인한다.

고정 버전·독립 배포가 필요하면 설치기의 기존 프로젝트 copy 모드를 사용하거나 `python -B scripts/build_project_template.py --mode snapshot --project-root <별도_시작팩>`으로 두 런타임의 21개 스킬 사본을 만든다. 기본 모드는 skills/pipelines.json의 project_template.mode=shared다. --check는 읽기 전용이며, --prune은 이전 manifest 지문과 일치하는 생성 파일만 정리한다. 사용자 수정·추가 파일은 보존한다. 기존 프로젝트 사본과 공용 등록을 병용하면 이름이 중복될 수 있으므로 차이를 검토한 뒤 전환한다.

스킬은 필요한 태스크에서만 읽는다. 전체 설계 파이프라인과 추적 규약을 매 요청마다 실행하지 않는다. 도구 사용 권한은 현재 런타임과 태스크 범위를 따른다.

## 선택형 추적 모드

감사 근거·요청 이력이 필요한 프로젝트는 workflow_mode: tracked 또는 기존 필수 규약을 사용한다. 이때만 [TRACEABILITY.md](policies/TRACEABILITY.md)를 읽고 아래 도구를 설치한다.

| 자료 | 용도 |
|---|---|
| graph/edges.csv | 발견·결정·매핑의 빈 대장 |
| graph/checks_config.template.json | 실제 프로젝트에 맞춰 채울 검사 예제 |
| tools/graph_checks.py | 설정된 무결성 검사 |
| [tools/ledger_query.py](tools/ledger_query.md) | 기본 open·지정 ID·관련 항목만 읽기 전용 조회 |
| logs/files.jsonl, logs/prompts.jsonl | 기존 v2 호환 append-only 로그 |
| tools/worklog/ | 로그 스키마·검증기 |

검사 설정은 실제 경로로 채우거나 사용하지 않는 검사를 제거한 뒤 graph/checks_config.json으로 저장한다. 로그는 메인이 작업 단위로 모아 기록하고 마감 시 한 번 검증한다. known_open 등록은 결함 해결이나 전체 품질 통과를 뜻하지 않는다.

```powershell
python -B tools/ledger_query.py
python -B tools/ledger_query.py --id F-001 --related --format md
```

조회는 ID 발급·대장 수정을 하지 않는다. 도구 내부에서는 CSV 전체를 검증하고 해시를 계산하지만, 에이전트에는 필터·페이지 결과만 전달한다. 페이지 사이 원본 해시가 바뀌면 다시 조회한다.

## 선택형 UF 뷰

`uf.md`가 정본이며 `uf_split/`은 요청이나 프로젝트 규약이 선택했을 때만 생성한다. 필요하면 설치된 uf-designer의 `scripts/uf_views.py rd/uf.md`를 사용한다. 생성 뷰가 있으면 `--check`로 원본·뷰·소유권 메타데이터의 무결성을 확인한다. 일반 작업에서 뷰가 없으면 SKIP이며, 프로젝트가 필수로 지정한 경우만 `--check --required`를 사용한다. 자세한 계약은 설치된 uf-designer의 `references/uf_views.md`를 따른다.

기존 빈 디렉터리·로그는 선택형 시작 자원으로 유지한다. 모든 프로젝트가 이를 복사하거나 사용해야 하는 것은 아니다. rd/, reports/, review_docs/, output_docs/는 새 문서를 만들 때의 관례이며 사용자 지정·기존 정본을 옮기는 근거가 아니다.
