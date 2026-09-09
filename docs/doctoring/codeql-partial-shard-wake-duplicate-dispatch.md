# CodeQL partial-shard wake duplicate dispatch RCA

## 관찰

2026-09-09 중앙 PR #2052의 required run `34316109112`가 exact head
`4833e6c202aaa02817b5b241178adb1facc6bf2a`와 base
`7fd571dbcdbae6acf29d8f4ee704d7ba6297e4db`를 대상으로 dispatch
`34316388553`을 만들었다. Python job `102353967729`는 05:58:54Z에
성공했고 05:58:50Z에 required job을 깨웠다. Actions job
`102353967703`은 06:01:09Z에 시작했지만, 같은 immutable run title을 가진
두 번째 dispatch `34317266381`가 06:01:38Z에 생성되면서 첫 실행이
06:02:08Z에 `cancelled`로 끝났다. Actions의 CodeQL analysis step도
`cancelled`였으므로 terminal success나 SARIF 증거로 계산하지 않는다.

## 원인과 수정

각 matrix shard의 exact-job wake는 독립적이지만 required workflow의
coordinator는 sibling shard가 아직 실행 중인지 확인하지 않았다. partial
success가 required rerun을 일으키면 coordinator가 남은 언어를 다시
dispatch했고, workflow/repository/PR 단위 `cancel-in-progress`가 같은
exact identity의 기존 실행을 successor로 오인해 취소했다.

coordinator의 기존 live PR·status·job-id 검증 뒤에 중앙 dispatch run 목록
검사를 추가했다. repository, PR, live head, live base, required run id가
run title에서 모두 일치하고 상태가 queued/running 계열이면 POST 없이 기존
실행을 보존한다. 다른 identity와 terminal-cancelled 실행은 새 dispatch를
막지 않는다. concurrency 계약이나 wake 독립성은 바꾸지 않았다.

## 재현과 검증

- RED: `test_codeql_coordinator_does_not_cancel_an_identical_active_dispatch`
  — 기존 coordinator가 두 번째 POST를 남겨 실패했다.
- GREEN: 같은 테스트와 기존 one-dispatch, all-terminal skip 계약 세 개가
  `3 passed`로 끝났다.
- 보호 branch, hosted workflow, sibling SARIF 성공은 새 commit의 Checks와
  실제 merge 뒤 별도로 확인해야 한다. 이 문서는 그 결과를 선반영하지 않는다.
