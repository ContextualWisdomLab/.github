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

## Verification

The permanent contract test forbids `NOEMA_REPAIR_DEADLINE_SECONDS`, `_repair_wall_clock_deadline`, `NoemaRepairDeadlineExceeded`, `signal.setitimer`, retry-only parameters/recursion, and caller-specified `temperature`. Focused regressions prove one request on success and failure, one annotation per attempt, safe serving-model telemetry, strict missing-value rejection, accepted genuine trailing commas, and preserved exact changed-line diagnostics.
