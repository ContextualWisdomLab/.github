## Fixed

- 중앙 `Security Scan`의 Gitleaks PR 범위를 오래된 webhook base SHA가 아니라
  인증된 live PR base와 exact head의 merge base에서 계산하도록 수정했습니다.
- base가 API 조회와 fetch 사이에 이동하거나 PR/head/repository identity가
  일치하지 않으면 비밀 검사를 우회하지 않고 명시적으로 fail closed 합니다.
