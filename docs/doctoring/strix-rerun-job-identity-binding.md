# Strix 재실행 대상 job의 신원 결합

## 확인한 결함

현재 main `ee5567f7b15f0441a61ec2435415603b9518f1c6`과 #1902의
`951d0ecd1b5398a9eac293a13bba220a6528df24`에서 Strix 재실행 선택 경로를 비교했다.
관련 core 차이는 이전 OPEN-state 수리뿐이었다. 이번 작업은 951 위에서 진행하며
main을 merge하거나 다른 세션의 workflow 변경을 덮어쓰지 않았다.

기존 선택기는 check의 details URL에서 job ID만 추출했다. 직전 live guard는
PR snapshot이 최신인지 확인했지만, 선택한 job이 그 PR head를 스캔했는지는
확인하지 않았다. 로컬 mock-only 회귀에서 실제 caller와 rerun wrapper를 실행한
결과 8 failed / 2 passed였다. 실패 사례는 job/run 조회 없이 mock POST에 도달했다.
실제 GitHub 위조 요청이나 job 재실행을 실행한 결과가 아니다.

## 최소 수리와 보류 조건

기존 selector와 API 조회 helper를 유지하고 Strix rerun 분기에 검증 하나를 추가했다.
GraphQL과 REST 정규화는 selected check의 database ID를 보존한다.

- selected check URL은 같은 repo의 정확한 run/job을 지정해야 한다.
- 실제 job의 ID, run ID, 이름, 완료 상태와 재실행 가능한 실패 결론을 확인한다.
  현재 허용 결론은 failure, cancelled, timed_out이다. 다른 결론은 자동 재실행을 보류한다.
- job이 가리키는 실제 check ID가 selected check와 같아야 한다. Check publisher는
  github-actions여야 하며 check suite와 run의 연결도 일치해야 한다.
- 실제 run과 workflow 조회는 같은 repo의 `.github/workflows/strix.yml`,
  `Strix Security Scan` 이름을 확인한다.
- pull_request_target은 정확히 하나의 PR association, base/head repository,
  association의 PR head, event에서 생성한 정확한 run-name이 모두 일치해야 한다.
  job/run의 top-level head_sha가 base SHA인 정상 사례를 허용한다. 이 필드를
  PR head로 간주하지 않는다. 누락되거나 상충하는 repository 식별자는 거부한다.
- repository_dispatch는 제어 코드의 실행 SHA만으로 target head를 증명할 수 없다.
  이 경로에는 인증된 target receipt를 소비하는 계약이 없으므로, 제목이 맞더라도
  자동 재실행을 보류한다. push 등 다른 event도 새로 허용하지 않는다.
- 검증이 끝난 뒤 live PR을 다시 확인한다. API 실패나 불완전한 metadata는
  `identity_unverified`로 보류하고 새 dispatch로 우회하지 않는다. 세 상위 caller도
  이를 실행 완료가 아닌 wait로 보고한다.

## 검증과 한계

`tests/test_strix_job_binding.py`는 실제 REST 정규화, selector, live guard,
dispatch caller, actor 검사, rerun wrapper를 실행한다. 외부 명령은 모두 mock 경계에서
차단한다. 정상 대조군은 top-level base SHA와 PR head SHA, REST repository URL 형식을
포함한다. 음성 사례는 stale·상충·누락·다른 repo/workflow/publisher/event·API 실패 및
검증 중 head 이동을 포함한다. 정상 사례는 네 metadata GET과 단일 mock POST를 요구한다.

기존 state-only, 명령형식, sibling 선택 테스트 세 곳은 각자의 검증 대상을 유지하도록
새 guard만 국소적으로 대체했다. 신원 결합 자체는 별도 회귀에서 실제 구현을 사용한다.

권한, 토큰 선택, actor allowlist, queue, concurrency, CodeQL primitive는 변경하지 않았다.
조회와 POST 사이의 원자성, cross-repo callback 권한, hosted 복구는 해결했다고 주장하지
않는다. 신뢰할 provenance가 없는 역사적 run은 자동 복구가 보류될 수 있다.
