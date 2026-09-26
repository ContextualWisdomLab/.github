## Changed

- Noema token-lifetime, OpenCode Rust coverage, Strix changed-path 품질 검증을
  `Agent Review Runtime Quality CI`의 단일 exact-head runner로 통합했습니다.
- PR concurrency를
  `agent-review-runtime-quality-{repository}-{PR번호}`와
  `cancel-in-progress: true`로 고정해 같은 PR의 구형 품질 실행만 취소합니다.
- 중복 checkout·Python setup·dependency boot와 Strix 전 저장소 test 실행을 제거하고,
  변경 파일에 맞는 영구 계약만 선택 실행합니다.
