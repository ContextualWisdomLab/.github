# 구매 시황 중앙 CI: current source candidate

상태: 로컬 구현 / 독립 재검토 대기 / ACTIVATION HOLD.

## PRD와 실패 계약

| ID | 요구 | 실패 상태 |
|---|---|---|
| CI-01 | 중앙 reusable `workflow_call` 전용, contents read | 임의 입력·secrets·hosted fallback 수용은 실패 |
| CI-02 | 고정 제품 repository, same-repo PR 또는 master push | 누락 PR head/base/number/SHA, fork, deleted push, malformed ref는 nonzero |
| CI-03 | Python 3.12/3.14, lock/frozen install/full pytest/Ruff/Node | missing/skipped/cancelled/failed leg는 acceptance 실패 |
| CI-04 | defining workflow 신원과 제품 head 분리 | mutable central ref, 없는 defining identity, head 대신 merge SHA는 거절 |
| CI-05 | 승인된 runner group/labels/격리 | provisioning 또는 canary 없으면 UNAVAILABLE |
| CI-06 | personal LiteLLM `auto` + 저자와 다른 독립 App | 실제 inference·substantive verdict·APPROVED가 없으면 미완료 |
| CI-07 | hosted-only 절차 retirement | 사라진 증거는 unavailable, 성공/skip으로 대체 불가 |

## 현재 실행 가능한 로컬 계약

- 준비 단계는 원래 `github.workspace` 바로 아래 새 checkout 디렉터리와 `runner.temp` 바로 아래 새 private 디렉터리를 만든다. 디렉터리가 이미 있으면 실패한다. 이전 Git hooks/config를 실행하거나 지우지 않는다.
- `GITHUB_WORKSPACE`/`RUNNER_*`를 덮어쓰지 않는다. 경로는 `steps.prepare.outputs`로 전달한다. checkout 상대 경로는 workspace 안에 있고, 품질 shell마다 `working-directory`를 명시한다.
- setup-uv의 실제 cache-local-path는 준비 단계가 만든 private root 아래다. cache restore/save를 끈다. HOME·venv·pytest·cache는 같은 실행별 private root 아래다.
- Cleanup은 실제 준비 단계 출력과 run/attempt/matrix identity를 대조한다. 다른 경로·traversal·symlink는 거절하며 foreign sentinel을 보존한다. output 쓰기 실패 시 준비 단계가 만든 디렉터리만 rollback한다.
- PR 원본 필드를 별도 전달한다. `|| github.repository`/`|| github.sha` fallback이 없다. PR head와 push/merge SHA를 다른 fixture로 실행해 검증한다.
- 다섯 품질 shell의 실제 body를 합성 uv/node 실행 파일로 실행한다. 각각 exit0 및 exit37 전달을 확인한다. 이 테스트는 실제 제품 검사/Actions 실행이 아니다.
- 중앙 정의는 GitHub 공식 `toJSON(job)`을 환경값으로 받아 documented workflow identity 필드를 명시적으로 검증한다. 누락·잘못된 타입·mutable ref는 실패한다. caller identity로 fallback하지 않는다. actionlint ignore는 사용하지 않는다.

## 소유 및 승인 경계

- 제품 caller: `ContextualWisdomLab/procurement-workbench` PR #4. 현재 파일 미수정.
- shared runner policy: 중앙 #2565. 기존 파일 미수정.
- LiteLLM service-key/transport/auto/App custody: 중앙 #2560. 키 중복 발급·Secret 덮어쓰기 없음.
- runner/isolation: `ContextualWisdomLab/linux-cluster-ops#326`, `ContextualWisdomLab/quarantine-sandbox-runtime#136/#137`.
- owned source: workflow, 두 procurement 계약/lifecycle test 파일, GOAL.md, 이 기록과 context 기록.

## 과거 실패와 이번 수리

R1에서 stale Git hooks, 공유 HOME cache, cleanup traversal을 지적했다. R2는 실제 prepare가 `/source/private`를 export하고 cleanup이 `/source.private`를 기대하는 연결 결함, checkout의 workspace 외부 경로, PR fallback을 재현했다. R2의 20개 테스트 통과는 이를 검증하지 못했다. 해당 보고서/해시는 scratch에 보존한다.

R3는 준비→출력→checkout path admission→effective cache→cleanup을 한 lifecycle로 연결한다. frozen R2 prepare0/cleanup1을 parent가 재현했다. pinned checkout input helper의 실제 코드에 R3 경로를 전달한 별도 scratch probe는 exit0을 반환했다. Portable repository tests는 개인 scratch 절대 경로에 의존하지 않는다.

## 미완료 acceptance

로컬 테스트·actionlint·독립 source verdict, 실제 runner/group/ACL/isolation/cleanup canary, immutable 중앙 게시와 protected integration, 제품 caller 및 check mapping, matrix 전체 실제 실행, hosted-only retirement, literal `auto` inference와 독립 App `APPROVED`는 서로 다른 gate다. source-only 통과로 나머지를 완료라 하지 않는다. Issue #5 STARTUP_FAILURE 원인은 별도 미확정이다.

Host 격리는 shell 디렉터리 검증만으로 증명되지 않는다. 악성 제품 code의 동시 경로 교체·호스트 조작·강제 종료 cleanup은 provisioning 격리/ephemeral reset 책임이다. Matrix skipped/missing은 원격 receipt 및 protection mapping에서 거절해야 한다.
