# CodeQL dispatch wake coordination and base-binding RCA

## 관찰

2026-09-09 중앙 PR #2052의 required run `34316109112`가 exact head
`4833e6c202aaa02817b5b241178adb1facc6bf2a`와 base
`7fd571dbcdbae6acf29d8f4ee704d7ba6297e4db`를 대상으로 dispatch
`34316388553`을 만들었다. Python job `102353967729`는 05:58:54Z에
성공했다. Actions job `102353967703`은 06:01:09Z에 시작했지만 같은
immutable run title을 가진 두 번째 dispatch `34317266381`가 06:01:38Z에
생성됐고 첫 실행은 06:02:08Z에 `cancelled`로 끝났다. Actions의 CodeQL
analysis step도 `cancelled`였으므로 terminal success나 SARIF 증거로
계산하지 않는다.

초기 수리는 언어별 wake를 없애고 `validate-dispatch`와 전체 `scan` matrix가
종료된 뒤 `wake-required-codeql` coordinator 하나가 exact required run의
`rerun-failed-jobs`를 한 번 호출하도록 바꿨다. required workflow의
coordinator는 같은 repository, PR, head, base, required-run tuple을 가진
queued/running dispatch가 이미 있으면 새 POST를 만들지 않는다. 다른
identity와 terminal-cancelled run은 fresh dispatch를 막지 않는다.

## 동일 head의 base retarget gap

PR #2051의 `927a9e35ed5c5e115a6c9d9b9f0035c7a0c0917e`에서 post-matrix wake는
live PR state와 head SHA, required run id/event/path/head/status, failed job
identity를 다시 검증했지만 base SHA를 wake identity에 포함하지 않았다.
GitHub의 실제 required run `34318639845`는 `pull_requests[]`에 PR number와
head/base SHA를 함께 제공하므로 base provenance를 별도 추정할 필요가 없다.
같은 head를 유지한 채 PR base만 retarget하면 이전 base의 completed run이
새 base의 wake를 승인할 수 있는 TOCTOU가 남아 있었다.

Test-only RED `901af9f024836eadd10c6c98affbee037ffecd58`은 두 경로를 고정한다.
하나는 validate 뒤 live PR base만 바뀌는 경우, 다른 하나는 live PR은 현재
base지만 supplied required run이 다른 base에서 만들어진 경우다. 기존 exact
wake block을 fixture-backed `gh api`로 실행하면 두 경우 모두 return code 0과
`rerun-failed-jobs` POST 1건을 남겼다.

`66a15d856c251f1db2f91cb3d4a2fa66afd8f48c`는 `validate-dispatch.outputs.base_sha`
를 wake job에 전달하고 다음을 모두 fail-closed로 결속한다.

- live PR은 open이고 `base.sha == BASE_SHA`, `head.sha == HEAD_SHA`여야 한다.
- exact `REQUIRED_RUN_ID`는 pull_request event의 `codeql-pr.yml` completed run이며
  `pull_requests[]` 안에 같은 PR number/head/base tuple이 정확히 하나 있어야 한다.
- 그 뒤에만 기존 failed-job id/name/run/head 검증과 run-level
  `rerun-failed-jobs`가 실행된다.

같은 fixture를 repaired block에 적용하면 두 changed-base 경로 모두 return
code 1, POST 0건이다. 기존 wake fixture도 같은 base-aware payload를 사용하도록
`f9d46984e1ef35341e9535af245da8e6ab9c061e`에서 보강했다. 이 검증은 hosted
required-check GREEN이나 protected merge를 대신하지 않는다.

## 경계와 기각한 대안

- head SHA만으로 current identity를 정의하지 않는다. GitHub PR은 head를
  유지한 채 base가 바뀔 수 있다.
- old-base run을 허용한 뒤 새 scan이 언젠가 덮을 것이라고 가정하지 않는다.
  required status는 exact base provenance를 잃으면 즉시 fail-closed해야 한다.
- polling, `sleep`, broad workflow rerun, manual/no-op trigger를 추가하지 않는다.
- concurrency key를 head/base까지 확장하지 않는다. genuinely superseded PR head는
  기존 workflow/repository/PR cancellation contract로 계속 정리한다.
- `pull_requests[]` base metadata가 없거나 모호하면 wake를 허용하지 않는다.

Hosted checks, independent review, protected-main integration과 실제 downstream
consumer rerun은 이 문서와 별도로 exact successor에서 검증한다.
