### 보안 검사 관측

- Guest 인증 경계에서 이미 존재하는 sandbox metadata만 제한된 형식으로 기록한다. 값은 cached 상태로 명시하며 민감한 본문이나 인증값은 기록하지 않는다.
- 모델·backend·ownership·cleanup·인증 결과·재시도·시간 제한은 변경하지 않는다. 진단이 지원되지 않거나 실패해도 원 scan 경로를 유지한다.
- 이 관측만으로 실제 Caido 장애 복구나 보안 검사 통과를 주장하지 않는다. [source·검증 한계](../docs/doctoring/strix-sandbox-lifecycle-diagnostics-20261002.md)를 참조한다.
