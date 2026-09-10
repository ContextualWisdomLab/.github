# Noema single-request review incident and telemetry contract

## Incident

On 2026-09-02, a required Noema review reported only a caller-owned 900-second repair deadline after a malformed structured response. The bound had no owner-specified or measured basis and conflicted with ADR-0003: model inference and repair verdict calls do not carry repository-authored fixed wall-clock deadlines.

```text
initial malformed structured response -> repository repair request -> fixed 900-second abort
```

The later review established a second ownership error: `contextual-orchestrator` already owns structured-output validation and its governed repair/failover. Issuing another repository-side model request duplicated that policy and could turn one gateway failure into two expensive calls.

## Final executable contract

Noema now sends exactly one structured-output request to the configured gateway. GitHub Actions fixes the model alias to `orchestrator/free`; the caller declares no provider, paid fallback, sampling temperature, or fixed inference timeout. `contextual-orchestrator` owns provider discovery, capability routing, structured-output repair, failover, and upstream completion. The repository remains responsible for deterministic local validation and exact-head publication.

Every gateway call emits exactly one passive Actions annotation. Success and failure annotations include caller attempt count, elapsed duration, active phase (`connecting`, `reading`, `decoding`, `validating`, or `response_error`), and a best-effort serving-model identifier. The identifier validator trims exterior whitespace, then accepts only 1–200 ASCII characters in its restricted identifier alphabet. Invalid text is omitted, not repaired. This is format and length validation, not arbitrary secret detection; the gateway must supply non-sensitive identifiers. Raw model output is never logged.

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

## 2026-09-05 follow-up: retain the gateway's error classification

Status: proposed consumer repair in [central PR #1898](https://github.com/ContextualWisdomLab/.github/pull/1898), not protected delivery or a resolved provider incident. This extends the evidence/control-plane requirement and G-02/G-03; ADR-0003's single-request ownership is unchanged.

### Observed failure and source trace

[Naruon #1244's failed job](https://github.com/ContextualWisdomLab/naruon/actions/runs/33933793278/job/101247827882) at head `50351e8cacc65b4124ba2145e00d41aeceef0775` reported HTTP 502, one caller attempt, `duration=1469.1s`, `phase=response_error`, and `served_model=deepseek-ai/deepseek-v4-flash-0731`. It did not preserve an error code or failure kind. The exception label `Noema gateway transport failed` therefore does not establish a network failure, nor does it establish structured-output exhaustion. That historical cause remains unknown.

Protected contextual-orchestrator source at `a080297d2546bb61e89520d637cabc202db331ec` already maps `ProviderResponseError` to HTTP 502 and the literal `invalid_structured_output` in [`server.py:7978`](https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/a080297d2546bb61e89520d637cabc202db331ec/contextual_orchestrator/server.py#L7978). [`_send_error`](https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/a080297d2546bb61e89520d637cabc202db331ec/contextual_orchestrator/server.py#L8189) adds a request identifier; [`_error_payload`](https://github.com/ContextualWisdomLab/contextual-orchestrator/blob/a080297d2546bb61e89520d637cabc202db331ec/contextual_orchestrator/server.py#L686) places the classification in canonical `error.code`. This path has no `failure_kind`, model, or attempt list. Those source facts identify an observable envelope, not the cause of the earlier Naruon run or an immutable release.

The original #1898 delta at `df0f735f42adbb44d45f3c3a4e503e400b47ed79` retains optional `error.detail.failure_kind`, but still discards `error.code`. Waiting only for contextual-orchestrator [#1004](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1004), whose proposed `36133c8ab85d44fc4be2356edbdd56d9fc09f0d8` adds `structured_output_exhausted`, would leave the existing protected-source envelope unclassified. Noema must not infer that kind from a status code, copy owner repair logic, or consume the proposed branch as a released dependency.

### Chosen repair and security boundary

The existing bounded reader and formatter now preserve both independent fields: `error.code` as `error_code`, and `error.detail.failure_kind` as `failure_kind`, when present and valid. The consumer repair is [commit `49ae54e789c0a6951b3212e2182e4c64d0348a81`](https://github.com/ContextualWisdomLab/.github/commit/49ae54e789c0a6951b3212e2182e4c64d0348a81). Both the single failure annotation and the raised diagnostic use the same extracted receipt. Missing fields remain absent; the failure still fails. No request, retry, provider selection, credential, timeout, or verdict-approval rule changes.

The reader requires canonical mapping envelopes including `error.detail`, reads at most 16 KiB plus one oversize-detection byte, and rejects malformed or oversized bodies. Each new field reuses the existing identifier validator; neither free-form messages, request identifiers, arbitrary detail, nor flattened compatibility aliases are logged. Embedded CR/LF, terminal escape sequences, surrogates, delimiter injection, non-string values, and overlength identifiers cannot enter the new fields. A syntactically valid secret placed in an allowlisted field would not be detected by this validator: non-sensitive canonical classifications remain a producer obligation.

This follows OWASP's advice to define log field types and lengths, validate data crossing trust zones, prevent log injection, and exclude credentials and sensitive payloads. It does not claim that a regular expression supplies complete redaction (OWASP Foundation, n.d.).

### Reproduction, integration, and remaining delivery gates

The existing failed-call regression covers 17 values for each independent field, plus those 17 values with the sparse current gateway envelope: 51 cases. It verifies annotation/exception output, absent sibling fields, one request/annotation, and exclusion of unrelated payload text. The sparse cases have a request identifier and compatibility aliases but no model, attempts, terminal reason, or failure kind. They address an independent static review's missing-fixture finding; they must preserve the code, report an unknown model, and exclude request-ID/message text. Unit-only HTTP doubles replace the external gateway; parsing, formatting, and `call_llm` execute normally.

Removing the original four `failure_kind` lines produced 3 failures; restoring them produced 138 focused passes. Adding canonical-code assertions to the old implementation reproduced 4 failures and 30 passes, including the actual protected-source code. Before the sparse-fixture extension, the consumer fix plus focused Noema edge coverage and the environment regression produced **159 passed, zero failures/skips**. With the sparse fixture added, removing just the four new code-extraction/formatting lines reproduced **8 failed / 43 passed**; restoring the implementation produced **51 passed**. These are chronological receipts, not totals for the final candidate.

The first broader run had **2897 passed, one skipped, 21 subtests passed, and one failure**: the task-local uv environment lacked `pip`, needed by `test_materialized_bounded_include_is_resolvable_by_pip`. The project already declares `pip==26.2.1`; installing that exact declared tool fixed the test without changing source, skipping it, or modifying a shared environment. The environment combines hash-locked review requirements and that separately declared pip pin; it is not claimed as an entirely hash-locked clean install.

The original PR delta and validation commit were preserved by ordinary merges. Protected main `f250638827f8252b0d9e5cb2601f4d333f96162f` (merged prerequisite #1922) is integrated at `719c91b1f678de6da3029b8f5920d6a245520e2e`. A preliminary normal run returned **2923 passed, one skipped, 21 subtests passed** before the sparse-fixture follow-up. The existing LLVM 19 admission test was skipped because its reviewed tools are absent on this macOS host; that path remains unverified, not passed. The separate maintainer exception reported for #1922 is not authorization to bypass #1898's gates. Full normal and `GITHUB_ACTIONS=true` verification must finish on the final integrated candidate, followed by fresh current-head hosted checks and qualifying independent review. Capture exact head/base and final command results in #1898; do not transfer old-head passes.

Run from the isolated repository root:

```sh
.venv/bin/python -m pytest -q -W error tests/test_noema_review_gate.py tests/test_noema_model_output_edge_coverage.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests -q -W error -rs
GITHUB_ACTIONS=true PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests -q -W error -rs
```

After protected delivery, confirm a real consumer run uses the exact released central revision and gateway contract. If it fails, retain the returned classification and investigate that owner path. Do not reroute to a paid model, repeat an active model request, weaken semantic validation, or declare the historical 502 repaired from unit evidence. Product runtime, real PostgreSQL, browser, release, and deployed-gateway verification are not covered by this consumer diagnostic test.

### Reference

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series. Retrieved September 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
