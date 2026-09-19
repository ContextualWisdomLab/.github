## Changed

- `CHANGELOG.md`에 `merge=union` 속성을 추가하고, union 병합이 제목을 코드
  펜스 안으로 삼키거나 빈 섹션을 만드는 경우를 감지하는 구조 계약을
  추가했습니다. 현재 changelog의 무펜스 구조를 유지하면서 독립 PR의
  prepend 충돌을 줄입니다.
