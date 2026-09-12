## Fixed

- 중앙 `Security Scan`의 Gitleaks PR 범위를 오래된 webhook base SHA가 아니라
  인증된 live PR base와 exact head의 merge base에서 계산하도록 수정했습니다.
- base가 API 조회와 fetch 사이에 이동하거나 PR/head/repository identity가
  일치하지 않으면 비밀 검사를 우회하지 않고 명시적으로 fail closed 합니다.

- PR checkout의 `.gitleaks.toml`은 실행 정책으로 신뢰하지 않고, 인증된 live base의
  설정만 별도 파일로 materialize하여 PR이 secret rule을 약화하지 못하게 합니다.
