# CodeQL SARIF 보존과 terminal 게시 경계

기준 `fe64f24931ec91b8578edb5b5eadf219074a52a7`의 handler는 gate가
성공하면 SARIF artifact upload 실패와 무관하게 success status를 게시했다.
게시 성공 조건만 보는 callback도 원래 required job을 깨울 수 있었다.

기존 upload action에 ID를 붙이고 실제 outcome이 `success`일 때만
terminal 게시를 허용한다. 실패·skip·누락·취소는 게시 전에 실패하며,
기존 callback의 publication-success 조건 때문에 wake도 실행하지 않는다.
정상 upload 뒤 gate의 success/failure/error 판정은 그대로 유지한다.
파일이 없는 upload도 성공으로 처리하지 않는다.

기존 `test_codeql_scan_dispatch_workflow_contract.py`의 실제 shell 추출과
fake-gh를 사용한다. upload failure/skipped/빈 값/cancelled 대조군은 수정 전
success POST와 mock wake가 발생해 RED였다. 외부 API나 실제 scan은 실행하지 않는다.

이는 전체 receipt 또는 dedupe 수리가 아니다. 기대 trusted workflow SHA의
독립적인 출처와 cross-repository artifact 읽기 권한은 여전히 후속 gate다.
기존 terminal status를 publisher·head·language만으로 재사용하여 다른
base/workflow의 성공을 승계할 수 있는 소비자 취약점도 이번 변경으로 해결되지 않는다.
동일 입력 증명, 자동 wake 재조정, admission 원자성도 이번 변경이 보장하지 않는다.
