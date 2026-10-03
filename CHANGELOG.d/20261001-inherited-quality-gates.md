### 검증·품질 게이트

- 상속된 CI helper의 CLI·오류·경계 테스트와 docstring 누락을 복구했다. Coverage 기준은 유지한다.
- 릴리즈 runtime 대상 집합을 파일 접근 전에 검증하고, 다운로드 응답의 오류 경로에서도 자원을 정리한다.
- Base와 이 수리의 로컬 전체 측정은 5,274 tests passed, statement·branch coverage 100%, docstring 100%다. 최종 결합 HEAD와 hosted 수용은 별도 검증 대상이다.
- 원인·RED/GREEN·검증 경계: [상속 품질 게이트 복구 기록](../docs/doctoring/inherited-quality-gates-20261001.md).
