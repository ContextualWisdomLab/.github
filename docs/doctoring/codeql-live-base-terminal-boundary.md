# CodeQL terminal 소비 전 live base 검증

기준 `b966f826085f8beabf4884e56ebca1d19b6c74e2`에서는 이미 조회한 PR의
state/head만 확인하고 terminal status를 소비했다. 이벤트 이후 base가
바뀌거나 base 정보가 없어도 trusted publisher의 같은-head 성공을 받아들였다.

기존 handler와 같은 base repository/ref/SHA 일치 계약을 소비 직전에 적용한다.
이미 받은 PR 응답을 사용하며 추가 API·권한·대기·자동 재dispatch는 없다.
누락·잘못된 자료형/SHA·불일치에서는 status 조회 전에 실패한다.

기존 실제 shell/fake-gh 테스트의 fixture를 production `PR_BASE_REF`,
`PR_BASE_SHA`, `PR_HEAD_REF` 이름으로 교정했다. live base 음성 8개와
event base 음성 3개가 RED였으며, 거부 경로는 PR GET 한 번만 허용해
status 조회 및 모든 POST가 없음을 확인한다. 정상 publisher·실패 verdict·
두 번째 페이지 status 회귀는 유지한다.

후속 exact-head 보안 검토에서 같은 head가 다른 base로 retarget된 뒤 이전
trusted status를 재사용할 수 있음이 확인됐다. Producer는 이제 exact head에
`codeql-dispatch/<language>/<base_sha>` context와
`cwl1;h=<head_sha>;w=codeql-scan-dispatch` receipt를 게시하고, target URL을
`ContextualWisdomLab/.github`의 숫자 Actions run ID로 제한한다. Consumer는
publisher identity와 이 네 필드를 모두 확인한다. 이전 generic context나 다른
base/head/workflow/target의 status는 terminal evidence가 아니며 bounded redispatch로
수렴한다. 실제 이전-base trusted success와 current-base trusted failure를 함께 둔
RED fixture가 이전 성공을 무시하고 현재 실패를 소비하는지 검증한다.

## Self-repository publisher identity amendment — 2026-09-08

`.github` PR #1962의 required run `34083528482`에서 child handler run
`34098416167`은 target-App status POST의 HTTP 403 뒤 repository
`GITHUB_TOKEN`으로 성공 receipt를 게시했다. 실제 creator는
`github-actions[bot]`이었고 exact job `101640519643`은 wake됐지만, consumer는
OpenCode App creator만 허용해 attempt-2 job `101722211580`을 terminal verdict
없는 rerun으로 거부했다. 게시 성공과 소비 가능한 identity가 분리된 것이 원인이다.

수리는 self repository에만 bounded fallback을 둔다. Consumer는 receipt의 숫자
run URL을 다시 조회하고 `repository_dispatch`, canonical workflow path, exact
repository/PR/head/base가 포함된 rendered title, OpenCode App actor와
triggering actor, `validate-dispatch`, 해당 language의 SARIF 보존 및 status 게시
step 성공을 모두 확인한다. Producer도 POST response의 creator를 확인한 뒤에만
publication success를 반환한다. 현재 handler 내부 settlement는 같은 self repo의
`github-actions[bot]` receipt를 현재 `GITHUB_RUN_ID` URL과 일치할 때만 받는다.

RED는 provenance가 완전한 self fallback 거부, 위조 workflow/title/actor 거부,
unrelated creator를 반환한 성공 POST의 오승인을 각각 재현했다. 다른 repository,
다른 run URL, 누락된 evidence step은 계속 fail closed한다. Bot creator를 전역
allowlist에 넣는 대안은 target workflow가 가진 `statuses:write`만으로 terminal
evidence를 만들 수 있어 채택하지 않았다.
