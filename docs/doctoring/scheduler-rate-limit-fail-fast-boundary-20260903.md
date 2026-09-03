# Scheduler primary rate-limit 무수면 경계

- 기준 저장소: `ContextualWisdomLab/.github`
- 기준 head: `main@2ed66f23362a759c49a95e2f919d36026866c642`
- 확인 시점: 2026-09-03 KST
- 상태: 구현 및 exact-head 검증 대상

## 장애 장면

`pr_review_merge_scheduler.py`는 GitHub App installation의 공유 primary rate limit이
소진되면 REST 또는 GraphQL 요청을 최대 네 번 시도했다. 재시도 전마다
`GET /rate_limit`을 읽고 최대 60초를 기다렸으므로, 하나의 논리 API 호출이 세 번의
대기 끝에 약 180초 동안 runner를 점유할 수 있었다.

이 동작은 60-job ceiling과 동시에 발생하면 다음 악순환을 만든다.

1. 공유 installation bucket이 이미 소진됐다.
2. scheduler runner는 성공 가능성이 없는 동일 bucket을 다시 사용하기 위해 대기한다.
3. 대기 중인 runner가 job slot을 점유해 다른 current-head 검증의 시작을 늦춘다.
4. 뒤따르는 scheduler·review workflow가 더 적체된다.
5. reset 뒤에도 오래된 실행부터 깨어나 최신 PR head 처리량을 잠식한다.

#1245는 조직 sweep이 첫 rate-limit repository에서 rotation을 중단하도록 개선했지만,
그 전에 개별 REST·GraphQL helper가 최대 세 번 sleep하는 구조는 보호된 `main`에
남아 있었다.

## 책임 분리

기존 5,700줄 규모 구현은
`scripts/ci/pr_review_merge_scheduler_core.py`로 이름을 명확히 분리한다. 기존
`scripts/ci/pr_review_merge_scheduler.py`는 외부 workflow command와 Python import를
보존하는 안정된 facade다.

- core: PR 조회·review 판단·dispatch·merge·branch update의 domain logic
- facade: 기존 CLI/import 계약과 운영 환경의 rate-limit retry policy

facade는 module proxy를 사용해 기존 테스트의 `monkeypatch.setattr(scheduler, ...)`를
core에 전달한다. 따라서 유효한 기존 단위 테스트와 소비자 import를 폐기하지 않는다.

## 선택한 정책

운영 CLI로 실행될 때 facade는 core의 REST·GraphQL helper에 다음 정책을 설치한다.

- `API rate limit exceeded` primary exhaustion은 첫 실패에서 즉시 상위 workflow로
  전달한다.
- reset 시각 확인을 위한 `GET /rate_limit` 추가 호출을 하지 않는다.
- primary rate-limit 경로에서 `time.sleep`을 호출하지 않는다.
- JSON 절단, 일시적인 server error, timeout 등 통신 장애에는 기존과 같은 최대 네
  번의 짧은 1·2·4초 재시도를 유지한다.
- 최종 RuntimeError 문자열을 보존해 조직 sweep의 typed defer 분기가 첫 repository에서
  rotation을 멈추고 다음 heartbeat로 넘기게 한다.

primary rate limit은 시간이 지나면 reset되지만, 현재 runner가 reset까지 점유되어야 할
이유는 없다. 이 변경은 재시도 자체를 없애는 것이 아니라, **성공 가능성이 없는 공유
bucket exhaustion**과 **짧게 회복할 수 있는 transport fault**를 분리한다.

## RED와 GREEN 계약

`tests/test_scheduler_rate_limit_fail_fast_entrypoint.py`가 다음을 고정한다.

1. GraphQL primary rate-limit은 요청 1회, sleep 0회로 실패한다.
2. REST primary rate-limit은 요청 1회, sleep 0회로 실패한다.
3. facade는 `/rate_limit` endpoint를 호출하지 않는다.
4. 일반 server error는 1초 뒤 한 번 재시도해 성공할 수 있다.
5. 기존 facade monkeypatch가 core에 전달된다.
6. dispatch source marker는 facade 문구만이 아니라 core 구현에도 실제로 존재한다.
7. 운영 entrypoint에 reset lookup이나 rate-limit sleep이 다시 들어오면 실패한다.

합성 package에서 facade import, proxy mutation, primary rate-limit fail-fast를 실행해
성공을 확인했다. GitHub exact-head checks가 runner 배정 전 queued이면 GREEN으로
간주하지 않는다.

## 영향과 후속 조치

primary rate-limit 한 건당 최악의 runner-held wait는 약 180초에서 0초로 줄어든다.
API 요청 수도 원 요청 최대 4회와 reset lookup 최대 3회에서 원 요청 1회로 줄어든다.

이 변경은 다음 별도 원인을 완결하지 않는다.

- `Wait for approved OpenCode publication run to finish` step의 최대 56초 polling
- org sweep 안의 중복 Actions run inventory와 stale cancellation
- Required OpenCode·Noema·Strix의 current-head admission과
  `cancel-in-progress: true`
- 동일 PR 상태를 여러 event가 깨우는 scheduler trigger fan-out

이들은 #1796 및 #712의 focused successor lane에서 계속 추적한다.

## Rollback

문제가 생기면 facade와 core 분리 commit 전체를 revert한다. core만 삭제하거나 facade만
옛 monolith로 되돌리면 import와 monkeypatch 경계가 갈라지므로 부분 rollback은 하지
않는다.
