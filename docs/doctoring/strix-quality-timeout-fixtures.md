# Strix quality timeout-fixture budget

검토 기준일: **2026-08-07**

## Incident

`Strix Changed Path Quality CI`는 실제 Strix 모델 스캔이 아니라 중앙 정책과 `scripts/ci/test_strix_quick_gate.sh`의 결정적 회귀를 검증하는 품질 게이트입니다. 그러나 테스트 하네스의 timeout fixture가 기본적으로 실제 프로세스 제한 30초와 가짜 sleep 60초를 사용하면서 여러 timeout/fallback 경로를 순차 실행했습니다.

PR #821 exact head `f92784f389317d512376a0725cbd78606b2e832c`의 품질 실행은 저장소 테스트 978개와 subtest 16개를 55.11초에 완료한 뒤 timeout fixture 구간을 수행하다가 job의 10분 제한에서 취소되었습니다. 동일 exact head의 rerun도 같은 단계에서 취소되었습니다. 이 결과는 소스 정책 실패가 아니라 결정적 테스트 fixture의 시간 스케일이 품질 job 예산과 맞지 않는다는 증거입니다.

## Decision

품질 workflow의 `Verify exact-head path policy and syntax` 단계에 테스트 전용 환경값만 전달합니다.

- `STRIX_TEST_PROCESS_TIMEOUT_SECONDS=3`
- `STRIX_TEST_FAKE_SLEEP_SECONDS=5`

`test_strix_quick_gate.sh`는 이미 두 값을 명시적 테스트 seam으로 제공하며, fake sleep이 process timeout보다 커야 한다고 fail closed 검증합니다. 따라서 timeout, cleanup, fallback의 순서와 결론은 그대로 유지하면서 wall-clock 대기만 축소합니다.

다음 production scanner 설정은 이 변경에서 건드리지 않습니다.

- `STRIX_PROCESS_TIMEOUT_SECONDS`
- `STRIX_TOTAL_TIMEOUT_SECONDS`
- `LLM_TIMEOUT`
- 실제 Strix workflow의 90분 process budget과 95분 total budget
- 모델, provider, credential, 권한, changed-path 정책 및 branch-protection 의미

테스트 전용 환경값은 해당 품질 step에만 존재해야 하며 production Strix 실행으로 전파되어서는 안 됩니다.

## Verification contract

`tests/test_strix_quality_timeout_fixture_budget.py`는 정확한 named step을 분리하여 다음을 고정합니다.

1. 짧은 process/fake-sleep fixture 값이 모두 존재합니다.
2. 하네스 실행이 같은 step에서 유지됩니다.
3. production timeout 변수는 해당 step에서 override되지 않습니다.
4. workflow trigger가 이 회귀 파일 자체를 포함하여 이후 변경이 정확한 품질 gate를 다시 실행합니다.

전체 `tests` suite, shell harness, Python compilation, Bash syntax 및 clean-worktree 검증은 계속 같은 exact-head quality step에서 수행합니다. 품질 gate의 성공은 실제 Strix 모델 security review, 독립 승인 또는 branch protection을 대체하지 않습니다.

## Coverage follow-up

stdlib `scripts/ci/portable_timeout.py` fallback은 subprocess 통합 테스트와
validation·signal forwarding·cleanup·deadline branch를 직접 실행하는
in-process 테스트를 함께 사용합니다. subprocess-only 테스트는 자식 프로세스
실행을 부모 coverage 보고서에 포함하지 않으므로, fallback을 omit하거나
100% threshold를 낮추면 미검증 제어 경로를 숨기게 됩니다. Fallback 변경 시
두 테스트 계층을 모두 유지합니다.

## Rollback

3초/5초 fixture가 GitHub-hosted runner에서 재현 가능한 race margin을 제공하지 못한다는 결정적 실패가 관찰되면 테스트 전용 값만 가장 작은 재현 가능한 상한으로 올립니다. production scanner timeout을 낮추거나 품질 테스트를 삭제하여 문제를 숨기지 않습니다. 10분 job timeout 자체를 늘리는 것은 fixture 가속으로도 완료할 수 없다는 실행 증거가 있을 때 별도 검토합니다.

## References (APA 7th)

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved August 7, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (n.d.). *Contexts reference*. GitHub Docs. Retrieved August 7, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/contexts

GitHub. (n.d.). *Viewing job execution time*. GitHub Docs. Retrieved August 7, 2026, from https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time
