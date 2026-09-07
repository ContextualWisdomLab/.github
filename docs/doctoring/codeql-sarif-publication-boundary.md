# CodeQL SARIF publication boundary

The central CodeQL dispatch handler publishes a terminal commit status only after the same matrix shard has successfully preserved its SARIF artifact. A successful finding gate without durable evidence is not a successful scan contract: upload failure, a skipped upload, cancellation, or a missing outcome fails closed before any status credential is used and therefore before the exact required job can be woken.

`actions/upload-artifact` owns the evidence boundary. The upload step has a stable step identifier and rejects an empty artifact input. The status-publication step consumes that step's outcome and accepts only `success`; it does not infer preservation from a generated local file or from the SARIF gate result. The gate result continues to determine whether preserved evidence represents a passing or failing security verdict.

Executable regression coverage runs the real publication shell against a fixture-backed GitHub API. The success control permits one exact-head status post. Upload outcomes `failure`, `skipped`, `cancelled`, and empty each exit before a post, preventing a false terminal success and the downstream exact-job rerun.

This source repair does not change repository-dispatch actor authorization or cross-repository credential authority. Those remain separate configuration and GitHub App permission boundaries tracked in ContextualWisdomLab/.github issue #1929.

## 로컬 회귀와 남은 경계

기준 `fe64f24931ec91b8578edb5b5eadf219074a52a7`의 실제 게시 shell은
upload failure/skipped/빈 값/cancelled에서 success POST와 mock wake가
발생해 RED였다. 통합 테스트는 이 네 조건과 정상 success, finding failure,
gate skipped의 error를 한 테이블로 검증하며 실제 게시 state와 mock wake를
함께 확인한다. 외부 API나 실제 scan을 실행한 증거는 아니다.

이는 전체 receipt 또는 dedupe 수리가 아니다. 기대 trusted workflow SHA의
독립적인 출처와 cross-repository artifact 읽기 권한은 여전히 후속 gate다.
기존 terminal status를 publisher·head·language만으로 재사용하여 다른
base/workflow의 성공을 승계할 수 있는 소비자 취약점도 이 업로드 수리로 해결되지 않는다.
동일 입력 증명, 자동 wake 재조정, admission 원자성도 보장하지 않는다.
별도 live base 검증의 범위는 [소비 경계](codeql-live-base-terminal-boundary.md)에 기록한다.
