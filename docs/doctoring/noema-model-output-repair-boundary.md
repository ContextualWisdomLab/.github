# Noema model-output repair boundary

## Incident

On 2026-09-01 the required Noema review for `ContextualWisdomLab/naruon#1505` reached deterministic verdict validation, rejected an adversarial-probe `outcome` outside the closed `falsified|confirmed` domain, then spent the repair path on a long second model call that ultimately surfaced only `HTTP 502 Bad Gateway`. That final transport symptom erased the more informative first trusted-validator failure from the top-level diagnostic.

## Decision

1. Model-produced JSON/envelope/schema/semantic-contract failures are `NoemaModelOutputError`; they remain fail-closed and are not consumer-source findings.
2. The primary review keeps the accepted contextual-orchestrator no-fixed-inference-timeout contract. The *single corrective attempt* is different: it repairs an already-completed verdict and therefore has one 900-second process-level wall-clock deadline across open/read/decode/validation. It deliberately does not use `urllib`'s renewable socket-operation timeout.
3. A corrective transport failure is `NoemaTransportError` and carries the sanitized first validator diagnostic plus the later transport exception class/status. Raw model output is never copied into public Actions diagnostics.
4. Exact-head validation before retry and before publication remains mandatory. All model traffic remains on contextual-orchestrator `orchestrator/free`.

## Verification

The #1617 regression first proved RED because `NoemaModelOutputError` did not exist. The repair adds focused cases for malformed-verdict typing, malformed-then-502 evidence preservation with the 900-second repair-only timeout, and repeated malformed output remaining typed and non-passing. The repository full coverage/docstring gate is run before the one-shot repair workflow commits the result.

## References

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). Internet Engineering Task Force.

Python Software Foundation. (2026). *urllib.request — Extensible library for opening URLs*. Python 3 documentation.


## Actionable diagnostic boundary

Corrective prompts need the deterministic *class* of a malformed verdict to repair it,
but do not need arbitrary model-produced values. Trusted structural validator messages
(such as a missing required field or an invalid adversarial-probe outcome class) remain
available after secret scrubbing. Unsupported decision values and unknown model-output
text are redacted to stable diagnostics, and a repeated invalid-model exception is raised
without retaining the raw model exception as an explicit cause. Tests use a sentinel value
to prove it reaches neither the retry prompt nor the final diagnostic.
