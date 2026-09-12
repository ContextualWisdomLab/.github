# Autoresearch 2026-09-10 — CodeQL SARIF gate rule-index hoist

- Owner: `ContextualWisdomLab/.github` (control plane, org `.github` special repo)
- Base HEAD: `f578d8d960177ff113c25fd740619b4a483df300` (`main`, `origin/main` 일치, 2026-09-10 KST 재조회)
- Branch: `autoresearch/20260910-kpi-loop` → experiment commit `91ee17a6e32f709702fc55db8c7f69cd4c3893a0`
- Gap linkage: G-03 (CI infra 결함 vs 보안 결과 구분 — gate 자체는 그대로, 오버헤드만 제거), G-04 (queue hygiene — dispatch 전 gate 지연 축소), G-09 (green CI ≠ 고객 정확성 — 정확성 가드레일 유지)
- PRD: PRD-05 제외 (이 레포는 제품 기능 미소유, control plane). TRD evidence/control plane 해당.
- Status: experiment 1 `keep`, PR 미오픈 (다음 단계에서 exact-head 증거와 함께 오픈)

## 1. 범위 (수정 / 읽기 전용)

- 수정: `scripts/ci/codeql_sarif_gate.py` 1개 파일만 (18 insertions, 7 deletions)
- 읽기 전용: `tests/test_codeql_sarif_gate.py`, `tests/test_filter_gitleaks_sarif.py`, `.github/workflows/codeql-*.yml`, `docs/product-technical-gap-baseline.md` (갱신하지 않음 — #2060 등 5개 오픈 PR과 경합 회피), 보호 브랜치 직접 push 금지, 공동 브랜치 reset --hard/force-push 금지 (본인 브랜치 단일 커밋만 유지)
- 측정기 변경 시 baseline 재측정 준수:旧 코드 `/tmp/baseline` worktree에서 동일 합성 SARIF로 재측정 (OLD mean=0.0716s)

## 2. KPI 정의 (분모·방향·명령·추출식·baseline·목표·제약·채택)

| KPI | 정의 (분모) | 방향 | 명령 | 추출식 | Baseline | 목표 | 제약 | 채택 기준 |
|---|---|---|---|---|---|---|---|---|
| 정확성 | targeted pytest 통과율 = passed/total (20) | higher | `.venv/bin/python -m pytest tests/test_codeql_sarif_gate.py tests/test_filter_gitleaks_sarif.py -q` | `(\d+) passed` | 20/20 (cold 5.83s, warm ~0.15s) | 20/20 유지 | 기존 테스트 전부 통과 | 1개라도 fail이면 기각 |
| 보안 | Medium+ gate 정확성 = fixture 기대 finding 집합 일치 | higher | 동일 targeted suite 중 `test_gather_findings_*`, `test_main_*` | assert 집합 동등 | 12/12 gate 테스트 GREEN | 회귀 0 | severity 임계값·억제(suppressions) 로직 변경 금지 | 의미 변경 없이 동일 출력 |
| 신뢰성 | coverage = covered stmts+branches / total (`codeql_sarif_gate.py`) | higher | `coverage run -m pytest tests/test_codeql_sarif_gate.py && coverage report --include="*/codeql_sarif_gate.py"` | `Cover` % | 100% (87 stmts, 32 branch) | 100% 유지 | `fail_under=100` | <100%면 기각 |
| 접근성 | docstring = 문서화된 public+private 함수 / 전체 (본 레포는 UI 없음, Figma N/A) | higher | `interrogate scripts/ci/codeql_sarif_gate.py` | `actual: 100.0%` | 100% | 100% 유지 | 새 함수 docstring 필수 | <100%면 기각 |
| 운영성 | gate CLI 정상 종료 = clean SARIF에서 exit 0 | binary | `gate.main([clean_dir]) == 0` (테스트 내) | exit code | 0 | 0 유지 | fail-closed 변경 금지 | non-zero면 기각 |
| 과업 성공 | 실험 GREEN = targeted 20 passed + coverage 100 + interrogate 100 | binary | 위 3개 명령 | AND | 1 | 1 유지 | 어느 하나라도 RED면 기각 | 부분 성공은 전체 승인 아님 |
| 성능 (primary) | `gather_findings` wall mean, 2000 results/200 rules, 5회 반복 mean (초) | lower | 합성 SARIF + `time.perf_counter()` 5회 (run.log 기록) | `mean=` | 0.0379s (stdev 0.0027) | ≤0.020s (≥40% 개선) | 정확성·보안·계약 회귀 금지 | 목표 달성 + 3회 독립 반복 모두 baseline 하회 |
| 비용 | CI 비용 proxy = 성능 시간 (무료 풀 `orchestrator/free`만, 유료 fallback 없음) | lower | 성능과 동일 | 동일 | 0.0379s相当, 유료 호출 0 | 시간 단축 + 유료 0 유지 | Actions `orchestrator/free` 고정, 공급자·모델·group명 하드코딩 금지 | 유료 호출 발생 시 기각 |
| 복잡도 | stmts + branch + 함수 수 (커버리지 리포트 + AST) | lower-or-equal | `coverage report` + AST 함수 카운트 | stmts/branch/funcs | 87/32/7, 135 LOC | 증가 최소화 (≤+5 stmts, branch +0) | 단순성 정책 (ugly complexity는 작은 개선과 맞바꾸지 않음) | branch +0, stmts +2 (89/32/8, 146 LOC) — 허용 범위 |

## 3. 실험 결과 (results.tsv)

```text
0  f578d8d9  0.0379  baseline  합성 2000/200 mean_s; 가드레일 20passed coverage100 interrogate100
1  91ee17a6e 0.0083  keep      rule-index hoist; 0.0379→0.0083s (~78%); 독립 3x 0.0062/0.0069/0.0094; 旧 worktree 0.0716; 가드레일 20passed coverage100 (89/32) interrogate100
```

- 오류를 0점으로 숨기지 않음. Cold-start 5.83s vs warm 0.10–0.24s 차이는 측정 아티팩트로 기록하고 primary 지표로 쓰지 않음.
- 우연 배제: 동일 합성 입력으로 3회 독립 trial +旧 코드 worktree 대조. 모두 신 코드 <旧 코드.

## 4. 변경 내용 (최소 수정)

- `_rules_by_id(rules)` 헬퍼 추가 (인덱스 1회 구축).
- `_rule_for_result(result, rules, rules_by_id)` / `_finding_from_result(result, rules, rules_by_id)`가 호출자가 준 인덱스 사용.
- `gather_findings`가 run당 1회 인덱스 구축 후 결과 루프에 전달. `ruleIndex` 폴백은 원본 `rules` 리스트 순서 그대로 사용하므로 의미 동일.
- 외부 호출자 없음 (`grep` 확인: `scripts/`, `tests/` 내 호출은 `gather_findings` 경유만). 시그니처 변경은 내부 전용.

## 5. 그래프 근거 (부분 조회, 전체 미적재)

- CodeGraph DB: `.codegraph/codegraph.db` (27MB, 2026-09-10 09:52), daemon live. `codegraph_explore "agent_mention_router performance regex hot path"` + `"codeql_sarif_gate _rule_for_result gather_findings"` 부분 조회만 사용. `graph.json`/`GRAPH_REPORT.md`/`graph.html` 전체를 컨텍스트에 적재하지 않음.
- EXTRACTED (원문 확인): `_rule_for_result`가 호출마다 dict comprehension 재구축 (lines 36–43旧), `gather_findings` 루프 구조 (lines 90–106旧), 테스트 12개가 `gather_findings` 경유만 검증.
- INFERRED: 대용량 SARIF에서 O(N·R) → O(N+R)로 개선 (실측으로 검증됨).
- AMBIGUOUS→해소: 테스트 wall 5.83s→0.24s는 코드 개선이 아니라 cold/warm 아티팩트임을 반복 측정으로 해소.
- 누락/stale: 전체 200개 오픈 PR의 파일 경합은 전수 대조하지 못함 (상위 20개 + `git log` 안정 파일로 회피). 그래프는 근거 색인이며 실행·릴리스 증거가 아님.

## 6. 검증

- `20 passed` (targeted 2파일), `coverage 100% (89 stmts, 32 branch)`, `interrogate 100%`.
- 합성 2000/200: baseline 0.0379s → 0.0083s, 독립 3x 모두 <0.01s, 旧 worktree 0.0716s.
- `git status` clean (tracked 변경 1파일 1커밋 외 `results.tsv`/`run.log`는 untracked + exclude).

## 7. 다음 Gap / CWL·Connector 연계

- 다음 후보: `filter_gitleaks_sarif.py::result_classifications`의 비-list `classifications` 강건성 (문자열 입력 시 문자 단위 분해 edge) — RED 케이스 추가 후 최소 수정. 단, 보안 게이트이므로 finding 검증→RED→GREEN 순서 준수.
- PR·Issues 소진 후에도 Gap G-05/G-06 (plugin manifest·standalone round-trip) 방향으로 naruon 소유 저장소와 연계. 본 레포에서는 계약 복제 금지, port·ACL·기능 플래그 경유.

## References

OASIS. (2022). *Static analysis results interchange format (SARIF) version 2.1.0* (OASIS Standard). https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html

Python Software Foundation. (2026). *Mapping types — dict* (Python 3.12 documentation). https://docs.python.org/3.12/library/stdtypes.html#mapping-types-dict
