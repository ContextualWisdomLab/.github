## Changed

- PR review merge scheduler의 구현을 안정된 CLI/import facade와 core 모듈로 분리했습니다.
- GitHub primary rate-limit 소진 시 reset 조회와 최대 약 180초의 runner-held sleep을
  제거하고 첫 실패에서 조직 sweep의 defer 경계로 즉시 반환합니다.
- 일시적인 server error·timeout에는 기존의 짧고 제한된 transport retry를 유지합니다.
- rate-limit 요청 1회·sleep 0회, legacy import·monkeypatch 호환성을 회귀 테스트로
  고정했습니다.
