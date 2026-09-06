# Noema single-request review incident and telemetry contract

## Incident

On 2026-09-02, a required Noema review reported only a caller-owned 900-second repair deadline after a malformed structured response. The bound had no owner-specified or measured basis and conflicted with ADR-0003: model inference and repair verdict calls do not carry repository-authored fixed wall-clock deadlines.

```text
initial malformed structured response -> repository repair request -> fixed 900-second abort
```

The later review established a second ownership error: `contextual-orchestrator` already owns structured-output validation and its governed repair/failover. Issuing another repository-side model request duplicated that policy and could turn one gateway failure into two expensive calls.

## Final executable contract

Noema now sends exactly one structured-output request to the configured gateway. GitHub Actions fixes the model alias to `orchestrator/free`; the caller declares no provider, paid fallback, sampling temperature, or fixed inference timeout. `contextual-orchestrator` owns provider discovery, capability routing, structured-output repair, failover, and upstream completion. The repository remains responsible for deterministic local validation and exact-head publication.

Every gateway call emits exactly one passive Actions annotation. Success and failure annotations include caller attempt count, elapsed duration, active phase (`connecting`, `reading`, `decoding`, or `validating`), and a best-effort serving-model identifier. Serving-model text is secret-scrubbed, control-character-normalized, UTF-8 printable, and bounded before it can reach an annotation. Raw model output is never logged.

The local trailing-comma parser remains a deterministic syntax transform only. It may remove a genuine trailing comma after a complete JSON value, but missing-value forms such as `[,]`, `{,}`, `[1,,]`, and `{"a":,}` remain invalid. The transform emits no second attempt-level annotation and never bypasses semantic verdict validation.

Exact changed-line diagnostics include the rejected path/line/side, an unambiguous array position, and a bounded nearest-line hint. This keeps a failed verdict repairable at the gateway without expanding the output contract to one record per changed line.

## Ownership and failure scenes

```text
Noema workflow -> local contextual-orchestrator sidecar -> orchestrator/free -> routed free candidate
               -> one returned envelope -> local deterministic validation -> exact-head publication
```

If the gateway cannot produce a valid structured verdict, Noema fails closed after that one caller request. If the PR head moves during model work, the post-call exact-head check discards the stale verdict. If telemetry carries hostile model identifiers, annotation sanitization prevents CR/LF or surrogate data from becoming workflow commands or crashing the runner.

## 응답 정리와 원래 오류 보존 — 2026-09-06

HTTP 오류는 예외이면서 읽을 수 있는 응답이기도 하다. 요청을 수행한
소유자가 필요한 제한 길이의 진단을 읽은 뒤 응답을 닫는다. 빌려 받은
스트림을 해석하는 함수에 정리를 떠넘기거나 가비지 수집 시점에 의존하지 않는다.
Noema뿐 아니라 정책 검사, Pages 검증, 격리 실행의 준비 상태 확인도 같은
소유권을 지킨다. 이들은 별도 요청 경계이므로 새 공통 클라이언트를 만들지 않았다.

기존 [PR #1879](https://github.com/ContextualWisdomLab/.github/pull/1879)의
`0723a0c7d9d4da82e64f884cff8babf1f0e0c81a`는 일반 응답 정리를 수행하지만,
정리 중 오류가 발생하면 원래 실패를 덮는다. 네 실제 호출 경계에 각각
`OSError`, `ValueError`, `RuntimeError`를 주입해 12개 실패를 재현했다.
응답 정리 한 문장에만 `contextlib.suppress(Exception)`을 적용하여 기존
통신 오류와 준비 실패 결과를 보존한다. `KeyboardInterrupt`와 `SystemExit`는
전파한다. 정리 시도 자체가 실패했을 때 모든 운영체제 자원이 반드시 해제됐다는
보장은 하지 않으며, 이를 성공한 요청으로 바꾸지도 않는다.

직접 redirect 예외를 만든 네 기존 테스트도 자신이 소유한 응답을 닫는다.
경고 필터나 수집기 강제 실행은 추가하지 않는다. URL·리다이렉트·프록시 정책,
재시도 횟수, 모델 제한 시간, 리뷰 내용 검증은 이 수정의 대상이 아니다.

회귀 검사는 `tests/test_http_error_response_ownership.py`에서 네 실제 호출자와
여섯 정리 결과를 교차 검증한다. 네트워크 요청만 대체하고 실제 HTTPError와
응답 스트림의 닫힘 상태를 확인한다. 전체 검증은 저장소 루트에서
`python -m pytest -q -W error --cov=scripts/ci --cov-branch --cov-fail-under=100`을
실행한다. 로컬 결과와 정확한 커밋은 PR에 기록하며 실제 공급자 호출·호스팅된
Checks·보호 병합의 근거로 대신 쓰지 않는다. Noema의 별도 schema 개선
[#1641](https://github.com/ContextualWisdomLab/.github/pull/1641)은 이 PR에 복제하지 않는다.

Python Software Foundation. (n.d.-a). *urllib.error — Exception classes raised by urllib.request*.
Retrieved September 6, 2026, from https://docs.python.org/3.14/library/urllib.error.html

Python Software Foundation. (n.d.-b). *contextlib — Utilities for with-statement contexts*.
Retrieved September 6, 2026, from https://docs.python.org/3.14/library/contextlib.html#contextlib.suppress

## Verification

The permanent contract test forbids `NOEMA_REPAIR_DEADLINE_SECONDS`, `_repair_wall_clock_deadline`, `NoemaRepairDeadlineExceeded`, `signal.setitimer`, retry-only parameters/recursion, and caller-specified `temperature`. Focused regressions prove one request on success and failure, one annotation per attempt, safe serving-model telemetry, strict missing-value rejection, accepted genuine trailing commas, and preserved exact changed-line diagnostics.
