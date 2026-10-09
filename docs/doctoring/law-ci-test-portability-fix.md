# Law CI test portability fix

## 범위

2026-10-05 KST. Dispatch `ctx_df60f6521590`.
기준 HEAD는 `9e482e14c3d31a09e9167af2fafb2edab26fbf12`다.
수정 파일은 `tests/test_law_ai_agent_ci.py`와 이 새 보고서뿐이다.
Git commit, push, 원격 게시, runner 설정, 제품 helper 변경은 하지 않았다.

GitHub에서 PR #2581의 head/base와 CodeRabbit comment `4181096101`을 직접 읽었다.
Finding은 유효했다. 기존 fixture는 `~/.hermes/cache/scratch`가 이미 있어야 했다.
해당 부모 디렉터리가 없으면 두 parametrize case 모두 child 실패 주입 이전에 실패했다.
CodeRabbit의 `/tmp` 고정 제안은 적용하지 않았다. 현재 TMPDIR와 canonical 경로 검증을 유지했다.

## RED → GREEN

실행 interpreter는 `/Users/seonghobae/.pyenv/versions/3.14.5/bin/python3`, Python **3.14.5**다.
환경 snapshot의 3.14.7과 구분한다. 실제 TMPDIR는
`/var/folders/vq/nxtc622x2lg1xq3jpdktymdw0000gn/T/`였다.

1. 새 subprocess 회귀 테스트를 먼저 추가했다. 빈 HOME, 긴 RUNNER_TEMP, 짧은 TMPDIR에서
   기존 실제 `test_synthetic_child_failure_and_cleanup_are_not_success[False/True]`를 각각 실행했다.
2. `python3 -m pytest tests/test_law_ai_agent_ci.py -q -k without_hermes_home`는
   **2 failed, 33 deselected**였다. 두 child 모두 `.hermes/cache/scratch/lf.*`에서
   **FileNotFoundError**였다. 이는 추정이나 별도 mock 재현이 아니다.
3. 테스트 전용 `short_temp_root()`를 추가했다. `tempfile.gettempdir()`의 resolved 경로를 우선한다.
   `l.` + 8자리 임시 이름과 `/lawci.XXXXXX`를 포함한 24자 예산을 적용한다.
   생성될 helper scratch는 기존 계약인 **65자 미만**을 유지한다.
4. 기본 temp 경로가 길면 HOME 아래 `.cache/law-ci-tests`를 canonical 경로로 선택한다.
   길이를 먼저 검사하고 mode 0700으로 생성한다. 기존 경로의 uid와 private mode도 검사한다.
   긴 HOME까지 허용하려고 `/tmp` alias나 제품 validator를 우회하지 않는다.
5. GREEN 회귀 child는 `--basetemp`를 지정해 pytest 자체 임시 파일과 helper scratch를 분리한다.
   두 case는 child exit **37**, stop 호출, stop 실패 시 보존, 재cleanup을 실제 helper로 확인한다.
   새 `keep` sentinel은 cleanup 이후에도 내용 `unrelated`를 유지한다.
   테스트 종료 시 TemporaryDirectory가 이번 실행 디렉터리만 제거한다.

## 최종 검증

| 명령/계약 | 실제 결과 |
|---|---|
| 원래 collection | 33 tests |
| 두 no-Hermes-HOME subprocess + 기존 두 failure case | 4 passed, 31 deselected |
| `python3 -m pytest tests/test_law_ai_agent_ci.py -q` | **39 passed, 10.18s** |
| `GITHUB_ACTIONS=true python3 -m pytest tests/test_law_ai_agent_ci.py -q` | **39 passed, 10.88s** |
| `git diff --check` | exit 0 |
| 추가 portability 계약 | short temp, symlink alias canonicalization, long temp fallback, TMPDIR 없는 default |

기존 33개와 새 6개가 모두 통과했다. Synthetic PostgreSQL 도구 결과를 실제 DB 실행으로 계산하지 않는다.
전체 중앙 suite/coverage는 중복 실행하지 않았다. Coordinator의 진행 중 baseline 결과와 별도다.
중앙 provider/model review timeout은 변경하지 않았다. 독립 리뷰와 보호된 원격 gate는 Coordinator가 소유한다.

## Exact bytes

| 파일 | SHA-256 |
|---|---|
| `tests/test_law_ai_agent_ci.py` | `e36b38d67befd4f591c2362fe2306430af8843d8028d7d13e3deb5429bfece79` |
| `scripts/ci/law_ai_agent_ci.sh` (변경 없음) | `7ee3d7d4f7083d87b921530f4ee3c7ce7dd8041e9611f4429390aa58f9e4e935` |
| `.github/workflows/law-ai-agent-ci.yml` (변경 없음) | `3aac714edfb5438c1f7c0eb6420fcff2f43b39692324cd6d7e86c4c103cfc164` |

보고서 자체의 SHA-256은 handoff에서 따로 전달한다.
