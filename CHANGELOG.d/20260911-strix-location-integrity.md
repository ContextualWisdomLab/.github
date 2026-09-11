## Fixed

- Strix 보안 finding의 `path:line` 위치를 실제 스캔 트리와 대조합니다. 모든
  위치가 존재하지 않거나 파일 끝을 넘으면 모델 inconsistency로 분류해
  재시도 가능한 non-passing 상태로 남기고, 유효·무효 위치가 섞이면 기존
  보안 차단을 유지합니다.
