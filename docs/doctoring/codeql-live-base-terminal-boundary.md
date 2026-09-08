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
`cwl1;h=<head_sha>;w=codeql-scan-dispatch;r=<required_run_id>` receipt를 게시하고, target URL을
`ContextualWisdomLab/.github`의 숫자 Actions run ID로 제한한다. Consumer는
publisher identity와 이 필드를 모두 확인한다. Handler run title도
target repository/PR/head/base/required run에 결속한다. 이전 generic context나 다른
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
repository/PR/head/base/required run이 포함된 rendered title, OpenCode App actor와
triggering actor, `validate-dispatch`, 해당 language의 terminal gate, SARIF 보존
step 성공과 exact run/attempt의 만료되지 않은 artifact를 모두 확인한다. Producer는
POST response의 creator를 확인한 뒤에만 receipt publication을 성공으로 인정한다.
현재 handler 내부 settlement는 같은 self repo의 `github-actions[bot]` receipt를
현재 `GITHUB_RUN_ID` URL과 일치할 때만 받는다.

Status POST가 모두 HTTP 403이면 receipt 자체는 만들 수 없다. 이 경우에도 동일한
현재 central run identity, successful validation, language gate, SARIF upload 및
exact unexpired artifact를 직접 재검증하면 terminal evidence로 인정한다. Scan
matrix는 `actions: read`만 가지며, 모든 language가 끝난 뒤 실행되는 단일 non-matrix
settlement job만 `actions: write`를 가진다. 이 경로는 bare 403, run URL 형태 또는
artifact 이름만으로는 열리지 않는다. Run, job, artifact 조회는 모두 native
pagination의 전체 page를 펼쳐 unique identity를 확인하며 첫 `per_page=100` 응답을
완전한 증거로 간주하지 않는다.

Coordinator의 scan matrix와 run-wide settlement map은 서로 다른 집합이다. Trusted
terminal receipt가 있는 language는 중복 scan에서 제외하지만, 그 language의 원래
compatibility job이 exact required run에서 실패했다면 `required_jobs`에는 유지한다.
반대로 성공 job과 language map 밖의 실패 job은 settlement 권한에 포함하지 않으며,
모든 pending language가 exact failed job에 매핑되지 않으면 dispatch 전에 실패한다.
이 구분이 없으면 Python receipt와 Actions pending이 섞인 경우 Actions만 재스캔한 뒤
불완전한 job map으로 run-wide settlement가 거부된다.

Target PR base SHA `A`와 중앙 handler workflow source SHA `S`도 분리한다. `A`는
target review base에 결과를 결속하고, `S`는 required workflow가 dispatch를 만든
시점의 immutable `github.workflow_sha`다. Producer는 `S`를 payload에 싣고 handler
title과 terminal receipt에 함께 결속한다. `repository_dispatch` receiver는 default
branch에서 실행되므로 runtime source `T`가 이후 전진할 수 있다. Handler와 모든
direct-evidence consumer는 `S == T`이거나 GitHub compare가 `S`를 `T`의 exact merge
base로 확인하고 `T`가 ahead이면서 behind가 아님을 증명할 때만 수용한다. 따라서
target base와 central source가 서로 달라도 유효하고, 호환되는 protected-main 전진
뒤에도 기존 immutable producer `S`를 보존한다. Diverged/reversed/missing/malformed
또는 조회할 수 없는 source 관계는 fail closed한다. 실제 target run `34186647327`의
`referenced_workflows=[]`는 source 부재를 뜻하지 않으므로 이 optional field나 현재
`main` tip을 source authority로 사용하지 않는다.

같은 required run을 recovery하면 incomplete predecessor와 successor handler가 동일한
bound title을 가질 수 있다. Consumer는 title 개수를 먼저 제한하지 않고 각 candidate의
run metadata, source ancestry, exact language gate, SARIF preservation, unexpired artifact를
검증한 뒤 evidence-complete candidate가 정확히 하나일 때만 verdict를 수용한다. 따라서
incomplete predecessor는 successor를 가리지 않으며 complete candidate가 0개 또는 2개
이상이면 계속 fail closed한다.

RED는 provenance가 완전한 self fallback 거부, 위조 workflow/title/actor 거부,
required-run 결속 누락, unrelated creator를 반환한 성공 POST의 오승인과 status
write 실패 뒤 직접 evidence 미검증을 각각 재현했다. 다른 repository, 다른 run
URL, 누락된 gate/SARIF/artifact는 계속 fail closed한다. Bot creator를 전역
allowlist에 넣는 대안은 target workflow가 가진 `statuses:write`만으로 terminal
evidence를 만들 수 있어 채택하지 않았다.

OpenCode App creator도 그 자체로 terminal evidence가 아니다. Shard와 coordinator는
App receipt에도 동일한 exact handler run, source ancestry, bound title, completed
language job, SARIF artifact 계약을 적용한다. 실제 RED는 올바른 App creator가 게시했어도
다른 workflow, 진행 중 job, 누락 artifact인 receipt가 이전에는 즉시 success로 수렴함을
재현했고, GREEN에서는 세 경우 모두 fail closed한다.
