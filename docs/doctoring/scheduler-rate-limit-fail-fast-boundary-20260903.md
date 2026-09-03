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

또한 `.github/workflows/opencode-review-dispatch.yml`의 caller가 scheduler CLI의
non-zero exit를 최대 세 번 다시 실행하며 5·10·15초를 추가로 기다렸다. helper 내부
대기만 제거하고 rate-limit을 exit 1로 반환하면 caller가 약 30초를 계속 점유하므로,
독립 리뷰에서 불완전한 수리로 판정됐다.

이 동작은 60-job ceiling과 동시에 발생하면 다음 악순환을 만든다.

1. 공유 installation bucket이 이미 소진된다.
2. scheduler runner는 성공 가능성이 없는 동일 bucket을 기다린다.
3. runner와 queue slot 점유가 current-head 검증 시작을 늦춘다.
4. caller retry와 후속 scheduler·review workflow가 더 적체된다.
5. reset 뒤에는 오래된 실행이 최신 PR head 처리량을 잠식한다.

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

운영 CLI에서 facade는 다음 정책을 적용한다.

- `API rate limit exceeded` primary exhaustion은 원 요청 한 번 뒤 즉시 중단한다.
- reset 시각 확인을 위한 `GET /rate_limit` 추가 호출을 하지 않는다.
- primary rate-limit 경로에서 `time.sleep`을 호출하지 않는다.
- `scheduler_outcome=deferred_rate_limit`과
  `retry_owner=next_bounded_heartbeat` receipt를 stderr와 GitHub step summary에 남긴다.
- typed defer는 현재 작업의 완료가 아니라 다음 bounded heartbeat로 책임을 넘긴
  **수락된 handoff**다. 그래서 CLI는 exit 0을 반환해 기존 caller의 외부
  5·10·15초 retry loop가 첫 호출에서 종료되게 한다.
- JSON 절단, 일시적인 server error, timeout 등 통신 장애에는 최대 네 번의 짧은
  1·2·4초 재시도를 유지한다.
- rate-limit이 아닌 RuntimeError는 exit 1을 유지해 실제 scheduler 결함을 숨기지
  않는다.

caller의 대형 workflow 파일을 부분 내용만으로 통째로 재작성하면 동시 delta를 잃을
위험이 컸다. 따라서 이번 수리는 stable CLI outcome contract에서 실제 30초 점유를
제거한다. 후속 owner lane에서는 caller의 죽은 retry loop 자체도 삭제해 source를
단순화한다.

## RED와 GREEN 계약

`tests/test_scheduler_rate_limit_fail_fast_entrypoint.py`가 다음을 고정한다.

1. GraphQL primary rate-limit은 요청 1회, sleep 0회로 실패한다.
2. REST primary rate-limit은 요청 1회, sleep 0회로 실패한다.
3. facade는 `/rate_limit` endpoint를 호출하지 않는다.
4. typed rate-limit defer는 exit 0, summary receipt, sleep 0으로 반환한다.
5. rate-limit이 아닌 RuntimeError는 exit 1을 유지한다.
6. 일반 server error는 1초 뒤 한 번 재시도해 성공할 수 있다.
7. 기존 facade monkeypatch와 wildcard import가 core API를 보존한다.
8. dispatch source marker는 facade 문구만이 아니라 core 구현에도 존재한다.
9. 운영 entrypoint에 reset lookup이나 무기명 defer가 다시 들어오면 실패한다.

합성 package에서 facade import, proxy mutation, wildcard export, typed defer를 실행해
확인했다. GitHub exact-head checks가 runner 배정 전 queued이면 GREEN으로 간주하지
않는다.

## 영향과 후속 조치

primary rate-limit 한 건당 helper 내부 최악의 runner-held wait는 약 180초에서 0초로,
caller의 실제 추가 wait는 약 30초에서 0초로 줄어든다. 원 요청·reset lookup을 합친
최대 7회 API 호출은 원 요청 1회로 줄어든다.

아직 별도 원인이 남아 있다.

- caller source에 남은 죽은 `for attempt`와 `sleep` 구문 삭제
- `Wait for approved OpenCode publication run to finish` step의 최대 56초 polling
- org sweep 안의 중복 Actions run inventory와 stale cancellation
- Required OpenCode·Noema·Strix의 current-head admission과
  `cancel-in-progress: true`
- 동일 PR 상태를 여러 event가 깨우는 scheduler trigger fan-out

이들은 #1796, #1706, #712의 focused successor lane에서 계속 추적한다.

## Rollback

문제가 생기면 facade와 core 분리, typed defer contract를 같은 revert로 복원한다. core만
삭제하거나 facade만 옛 monolith로 되돌리면 import와 outcome 경계가 갈라지므로 부분
rollback은 하지 않는다.
