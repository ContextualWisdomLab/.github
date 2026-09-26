# Scheduler primary rate-limit 무수면 경계

- 기준 저장소: `ContextualWisdomLab/.github`
- 구현 기준: PR #1803
- 확인 시점: 2026-09-03 KST
- 상태: exact-head 검증 대상

## 장애 장면

`pr_review_merge_scheduler.py`는 GitHub App installation의 공유 primary rate limit이
소진되면 REST 또는 GraphQL 요청을 최대 네 번 시도했다. 재시도 전마다
`GET /rate_limit`을 읽고 최대 60초를 기다렸으므로 하나의 논리 API 호출이 세 번의
대기 끝에 약 180초 동안 runner를 점유할 수 있었다.

또한 `.github/workflows/opencode-review-dispatch.yml`의 승인 후 best-effort caller는
scheduler CLI의 non-zero exit를 최대 세 번 다시 실행하며 5·10·15초를 추가로
기다렸다. helper 내부 대기만 제거하고 rate-limit을 exit 1로 반환하면 이 caller가
약 30초를 계속 점유하므로 독립 리뷰에서 불완전한 수리로 판정됐다.

반대로 모든 caller에서 rate-limit을 exit 0으로 바꾸면 조직 sweep의 rate-limit stop
signal을 잃는다. core는 mid-scan rate-limit을 non-zero로 전파해 현재 repository에서
rotation을 멈추고 같은 exhausted bucket으로 뒤 repository를 계속 읽지 않도록 한다.
따라서 defer outcome은 caller별 책임을 구분해야 한다.

## 책임 분리

기존 구현은 `scripts/ci/pr_review_merge_scheduler_core.py`로 이름을 명확히 분리한다.
기존 `scripts/ci/pr_review_merge_scheduler.py`는 외부 workflow command와 Python import를
보존하는 안정된 facade다.

- core: PR 조회·review 판단·dispatch·merge·branch update의 domain logic
- facade: 기존 CLI/import 계약, wildcard export, 운영 rate-limit retry/defer policy

facade는 module proxy와 `__all__`을 사용해 기존 attribute access,
`monkeypatch.setattr(scheduler, ...)`, wildcard import를 core에 연결한다. 따라서 기존
소비자 API와 유효한 단위 테스트를 폐기하지 않는다.

## 선택한 정책

모든 운영 CLI 호출에서 facade는 다음 transport 정책을 적용한다.

- `API rate limit exceeded` primary exhaustion은 원 요청 한 번 뒤 즉시 중단한다.
- reset 시각 확인을 위한 `GET /rate_limit` 추가 호출을 하지 않는다.
- primary rate-limit 경로에서 `time.sleep`을 호출하지 않는다.
- JSON 절단, 일시적인 server error, timeout 등 통신 장애에는 최대 네 번의 짧은
  1·2·4초 재시도를 유지한다.

rate-limit이 facade 경계까지 전파됐을 때 outcome은 caller identity로 분기한다.

### OpenCode 승인 후 best-effort follow-up

다음 조건을 모두 만족할 때만 rate-limit을 수락된 defer로 처리한다.

- `GITHUB_WORKFLOW`가 `OpenCode Review Dispatch`
- `--max-prs 1`
- `--review-dispatch-limit 0`
- `--merge-mode direct_or_auto`
- `--pr-number`, `--no-trigger-reviews`, `--enable-auto-merge`,
  `--no-update-branches`가 모두 존재

이 경우 `scheduler_outcome=deferred_rate_limit`과
`retry_owner=Required PR Review Merge Scheduler heartbeat` receipt를 stderr와 GitHub
step summary에 남기고 exit 0을 반환한다. 현재 follow-up caller는 non-zero에서만
5·10·15초를 기다리므로 실제 외부 sleep은 첫 호출에서 종료된다. PR-event와 scheduled
scheduler가 authoritative retry owner라는 caller source의 기존 설명과도 일치한다.

### 조직 sweep과 다른 caller

같은 rate-limit이라도 위 signature가 아니면 exit 1을 유지한다. 특히
`Required PR Review Merge Scheduler` 조직 sweep은 첫 rate-limit repository에서
rotation을 멈추고 다음 heartbeat로 defer하는 기존 #1245 계약을 보존한다.
워크플로 이름만 같거나 인자 일부만 비슷한 호출도 accepted defer로 오인하지 않는다.
rate-limit이 아닌 RuntimeError도 항상 exit 1이다.

caller의 대형 workflow 파일을 부분 내용만으로 통째로 재작성하면 동시 delta를 잃을
위험이 컸다. 따라서 이번 수리는 stable CLI outcome contract에서 실제 30초 점유를
제거한다. 후속 owner lane에서는 caller의 도달 불가능한 retry loop 자체도 삭제해
source를 단순화한다.

## RED와 GREEN 계약

`tests/test_scheduler_rate_limit_fail_fast_entrypoint.py`가 다음을 고정한다.

1. GraphQL primary rate-limit은 요청 1회, sleep 0회로 실패한다.
2. REST primary rate-limit은 요청 1회, sleep 0회로 실패한다.
3. facade는 `/rate_limit` endpoint를 호출하지 않는다.
4. 정확한 OpenCode follow-up signature는 exit 0, typed receipt, sleep 0으로 defer한다.
5. 조직 sweep rate-limit은 exit 1을 유지한다.
6. workflow 이름만 맞고 signature가 다르면 exit 1을 유지한다.
7. rate-limit이 아닌 RuntimeError는 exit 1을 유지한다.
8. 일반 server error는 1초 뒤 한 번 재시도해 성공할 수 있다.
9. 기존 facade monkeypatch와 wildcard import가 core API를 보존한다.
10. dispatch source marker는 facade 문구만이 아니라 core 구현에도 존재한다.

GitHub exact-head checks가 runner 배정 전 queued이면 GREEN으로 간주하지 않는다.

## 영향과 후속 조치

OpenCode 승인 후 rate-limit 한 건의 helper 내부 최악 wait는 약 180초에서 0초로,
caller의 실제 추가 wait는 약 30초에서 0초로 줄어든다. 원 요청·reset lookup을 합친
최대 7회 API 호출은 원 요청 1회로 줄어든다. 조직 sweep의 stop-and-defer signal은
그대로 남는다.

아직 별도 원인이 남아 있다.

- caller source에 남은 도달 불가능한 `for attempt`와 `sleep` 구문 삭제
- 승인 visibility 확인 step의 최대 30초 polling
- org sweep 안의 중복 Actions run inventory와 stale cancellation
- Required OpenCode·Noema·Strix의 current-head admission과
  `cancel-in-progress: true`
- 동일 PR 상태를 여러 event가 깨우는 scheduler trigger fan-out

이들은 #1796, #1706, #712의 focused successor lane에서 계속 추적한다.

## Rollback

문제가 생기면 facade와 core 분리, caller-scoped typed defer contract를 같은 revert로
복원한다. core만 삭제하거나 facade만 옛 monolith로 되돌리면 import와 outcome 경계가
갈라지므로 부분 rollback은 하지 않는다.
