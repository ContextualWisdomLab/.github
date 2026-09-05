# Noema model-output repair boundary

## Current contract (2026-09-02)

`.github` owns pull-request review orchestration, exact-head evidence, deterministic verdict validation, and publication. `contextual-orchestrator` owns provider discovery, capability routing, the `orchestrator/free` pool, structured-output repair, failover, and provider completion.

After `.github#1672` merged as `a28fc2f4e185df7847e2f2f5f6ec561d1e84805d`, Noema issues exactly one structured-output request for a review. The repository caller no longer performs a second model repair request and no longer installs a 900-second process-level repair deadline. There is no caller-owned fixed inference wall-clock deadline or sampling-temperature override; gateway/provider completion and the outer workflow lifecycle remain separate concerns.

The gateway response is still validated locally. A malformed or semantically invalid response fails closed with a bounded diagnostic containing the phase, elapsed duration, stable failure category, and served-model metadata when available. Raw model output and credentials are not written to Actions logs.

## Historical incident and the 900-second distinction

On 2026-09-01, `ContextualWisdomLab/html4tree` reached the old Noema corrective path after malformed JSON. The old caller then reported `NoemaRepairDeadlineExceeded` after a 900-second absolute wall-clock boundary. That boundary belonged to the superseded caller-side repair implementation; it is not a current Noema inference policy.

The same incident family also exposed real upstream failures: HTTP 413 `request_too_large`, Bytez discovery HTTP 500, NVIDIA timeout/429/404 responses, and malformed structured output. These are different failure classes and must remain visible as separate telemetry events rather than being collapsed into a generic timeout.

Three `timeout --kill-after=20 900` commands remain in `opencode-review-dispatch.yml`. They cap individual untrusted test-measurement shell commands in the coverage evidence job. They are not model requests, not Noema repair, and not a 900-second GitHub job timeout. Operational logs should describe them as sandbox command containment (for example, `sandbox_command_limit_seconds=900`) so an operator cannot mistake them for inference termination.

## Diagnostic and concurrency invariants

1. Model-produced JSON, envelope, schema, and semantic-contract failures remain fail-closed and are not consumer-source findings.
2. Every provider attempt reports a phase such as connecting, reading, decoding, or validating, its elapsed duration, a stable failure category, and the served model if known. Provider status classes such as 413, 429, 500, and 502 are retained as categories without copying provider secrets or raw model output.
3. The triggering pull-request head is checked before model work and again before publication. A push to the same PR makes the old head obsolete; the old run must not publish a verdict or spend a second repair call.
4. All model traffic for required review remains on contextual-orchestrator `orchestrator/free` and is subject to its discovery, capability, failover, and privacy policy.
5. A workflow shell timeout is evidence about that shell command only. It must never be used as evidence that the gateway or provider ended inference.

## Verification

The merged #1672 regression suite proves one gateway request, no caller-side retry/deadline/sampling machinery, sanitized model telemetry, strict local validation, bounded trailing-comma normalization, and exact changed-line diagnostics. A fresh exact-head Actions run is still required to establish hosted runtime evidence; queued or cancelled checks do not count as a pass.

Incident replay acceptance requires the log to distinguish at least: request_too_large, discovery_failure, rate_limited, provider_transport, malformed_model_output, stale_head, and sandbox_command_timeout. Each category must include phase and duration, while raw response bytes, credentials, and unbounded provider text remain excluded.

## References

Fielding, R., Nottingham, M., & Reschke, J. (2022). HTTP semantics (RFC 9110). Internet Engineering Task Force.

Python Software Foundation. (2026). urllib.request — Extensible library for opening URLs. Python 3 documentation.

## Actionable diagnostic boundary

Corrective prompts, when implemented by the gateway, may use the deterministic class of a malformed verdict but do not need arbitrary model-produced values. Trusted structural validator messages remain available after secret scrubbing. Unsupported decision values and unknown model-output text are represented by stable diagnostics, and raw model exceptions are not retained as public causes.