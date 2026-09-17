## Fixed

- PR review merge scheduler의 zero-diff 자동 종료가 base-to-head 비교만으로
  유효한 미병합 변경을 닫지 않도록 커밋 lineage와 파일 변경 근거를 다시
  확인합니다. lineage가 누락·잘림·오류이거나 커밋 단위 변경이 남아 있으면
  fail-closed wait 상태로 보존합니다.
