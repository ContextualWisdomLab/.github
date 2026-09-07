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

이 검사는 이벤트와 현재 live PR의 base 일치만 보장한다. 이전 verdict 자체가
어느 base/trusted workflow에서 생성됐는지는 증명하지 않는다. run-linked
receipt의 독립적인 기대 workflow SHA와 중앙 artifact 읽기 권한은 미결이며,
dedupe·자동 wake·admission 직렬화도 이번 범위가 아니다.
