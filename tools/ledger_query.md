# 대장 부분 조회

`ledger_query.py`는 표준 라이브러리만 쓰는 읽기 전용 도구다. 원본 CSV를 검사하고 필요한 행·열과 재현 정보를 stdout으로 보낸다. 원본을 수정하거나 ID·결과 파일을 생성하지 않는다. 기본 경로는 실행 위치와 무관하게 이 도구의 상위 프로젝트 `graph/edges.csv`다.

```powershell
python -B tools/ledger_query.py
python -B tools/ledger_query.py --id F-001 --id D-003 --related
python -B tools/ledger_query.py --status open --status deferred --query "인코딩"
python -B tools/ledger_query.py --id F-001 --columns id,status,title,notes,fix_ref --format md
python -B tools/ledger_query.py --status all --limit 25 --offset 25
python -B tools/ledger_query.py --ledger path/to/edges.csv --id F-001
```

- 기본 상태는 `open`이다. `--id`가 있고 `--status`를 생략하면 해당 ID를 모든 상태에서 찾는다. 반복 ID·상태 각각은 OR, ID·상태·검색 조건 간에는 AND다. `--status all`은 상태 제한을 없애며 다른 상태와 함께 쓰지 않는다.
- `--query`는 모든 열에서 대소문자를 구별하지 않는 문자열 부분 검색을 한다. 정규식·검색어 문법은 사용하지 않는다.
- `--related`는 먼저 조건에 맞는 seed를 고른 뒤 `notes`, `fix_ref` 등을 포함한 ID 외 모든 열의 F-/D-/M- 참조를 양방향·전이 탐색한다. 연결된 과거 결정·검증 근거를 잃지 않도록 확장 행에는 seed의 상태·검색 필터를 다시 적용하지 않는다. 순환은 중복 없이 끝난다. 실제 대장에 존재하는 ID만 연결하며 참조 형식은 `F-001`, `D-ABC`, `M-001-sub`처럼 영숫자 및 구분자 `-`, `_`를 허용한다. 자유 서술의 ID 언급도 연결로 해석하므로 정식 관계 증명으로 쓰지 않는다.
- 출력 순서는 원본 순서다. 기본 `--limit 50`, `--offset 0`이며 `limit`은 양수다. `matched`는 관련 확장 후·페이지 적용 전 행 수, `returned`는 이번 출력 행 수다. `has_more`와 `next_offset`으로 다음 부분을 조회한다. `truncated`는 앞이나 뒤의 일치 행이 생략됐는지 나타낸다.
- JSON이 기본이며 `--format md`는 같은 메타데이터와 표를 출력한다. 기본 보이는 열은 원본에 존재하는 `id,status,severity,title,location`이다. `--columns`로 상세 열을 요청할 수 있고 `id,status`는 항상 포함한다.
- `source.path`, 원본 바이트의 `source.sha256`, 필터, `total`, `seed_count`, `matched`, `returned`, 페이지 정보를 함께 보존한다. 페이지 사이 원본 해시가 바뀌면 첫 페이지부터 다시 조회한다. `missing_ids`는 대장에 없는 요청 ID다. 존재하지만 상태·검색에서 제외된 ID는 여기에 포함하지 않는다.
- UTF-8 및 UTF-8 BOM을 받는다. `id,status` 헤더와 각 행 값은 필수이며 상태는 `open/fixed/verified/rejected/superseded/deferred`다. 중복 ID·헤더, 필드 수 불일치, 잘못된 인코딩·CSV 등은 필터 밖의 행에서도 오류로 종료한다. 오류는 stderr의 JSON, 종료코드 2이며 stdout에 부분 결과를 남기지 않는다. 성공·0건 조회는 종료코드 0이다.

함수 사용 시 `query_ledger(path, ids=["F-001"], related=True, limit=20)`가 같은 사전을 반환한다. `statuses=None`은 위 기본 규칙을 따른다. 잘못된 입력은 `LedgerError`를 발생시킨다. 도구 내부에서는 검증·관계 탐색·전체 일치 수 계산을 위해 원본 전체를 읽지만 모델 문맥에는 선택한 출력만 전달한다.

검사: `python -B -m unittest discover -s tools/tests -p test_ledger_query.py -v`.
