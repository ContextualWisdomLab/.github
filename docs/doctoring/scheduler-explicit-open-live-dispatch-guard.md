# Scheduler의 명시적 OPEN·현재 head 확인

## 원인과 범위

#1902의 후속 조사에서 CodeQL 복구 primitive보다 먼저 고칠 공통 결함을 확인했다.
`4bf80b99b6908c0323ac406d7e30e8346e09a50d`의
`scripts/ci/pr_review_merge_scheduler_core.py`는 GraphQL 공통 PR fragment에서
`state`를 요청하지 않았고, REST PR 정규화에서도 그 필드를 보존하지 않았다.
그런데 `live_dispatch_head_matches`는 누락되거나 빈 state를 OPEN으로 취급했다.
단일 PR 조회는 닫힌 PR도 반환하므로 head가 그대로면 닫힌 PR을 허용할 수 있었다.
또한 양쪽 head를 빈 문자열로 대체해 비교했으므로 빈 값끼리도 일치했다.

영향 범위는 OpenCode repository dispatch, Strix의 기존 job rerun,
Strix repository dispatch 직전의 공통 guard다. 이번 수정은 이 세 경로의
새 실행 요청을 막는 조건만 다룬다. 앞서 수행되는 stale-run cleanup의 순서나
cancellation 정책은 바꾸지 않는다.

## 수정

- GraphQL 공통 fragment가 PR state를 실제로 요청한다.
- REST fallback은 원본 state를 대문자로 보존하고, 누락은 빈 값으로 남긴다.
- guard는 정확히 한 PR, 명시적 `OPEN`, 양쪽의 문자열 타입 40자리 hex SHA,
  대소문자를 제외한 동일 head를 모두 요구한다.
- 기존 정상 fixture는 `OPEN`을 명시한다. 누락 사례를 정상 fixture로 대체하지 않는다.

토큰, 권한, trigger, queue, concurrency, dispatch payload는 변경하지 않았다.
CodeQL primitive도 추가하지 않았다. 조회 직후 PR 상태가 바뀔 수 있는 경쟁 조건과
중복 전송의 원자성은 여전히 미해결이며, 이 guard는 exact-once 보장이 아니다.
Cross-repo target callback의 Actions-write 권한도 별도 미해결 조건이다.

## 회귀 검증

`tests/test_scheduler_live_dispatch_guard.py`는 실제 guard와 세 caller를 실행하고
외부 API 및 실행 요청만 대체한다. 누락·빈 값·CLOSED·MERGED·UNKNOWN은 dispatch와
rerun에 도달하지 않아야 하며, OPEN의 정상 경로는 계속 도달해야 한다.
별도 사례가 빈 값, 잘못된 길이, 비-hex, 비문자열, 서로 다른 SHA를 거부하고
GraphQL 실제 query와 REST fallback의 state 전달을 확인한다.

Production 수정 전 새 회귀는 17 failed / 19 passed였다. 이후 실제 live head만
잘못된 사례 두 건도 추가했다. 최종 관련 5파일은 `-W error`를 적용해 정상 환경에서
380 passed, `GITHUB_ACTIONS=true` 환경에서도 380 passed를 확인했다.
검증 명령은 다음과 같다.

```sh
python -m pytest -q -W error tests/test_scheduler_live_dispatch_guard.py tests/test_pr_review_merge_scheduler.py tests/test_strix_rerun_job_selection.py tests/test_repository_branch_coverage_review_schedulers.py tests/test_pr_review_fix_scheduler_rest_workflow_identity.py
```

로컬 회귀 통과는 실제 GitHub dispatch, protected merge, 대상 job 복구의 증거가 아니다.
