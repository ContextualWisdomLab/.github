# ADR-0009: Redact the complete sandbox evidence boundary while preserving diagnosis

Status: Accepted; [PR #1031](https://github.com/ContextualWisdomLab/.github/pull/1031) is the current open integration path; Draft [PR #906](https://github.com/ContextualWisdomLab/.github/pull/906) and [PR #888](https://github.com/ContextualWisdomLab/.github/pull/888) are closed unmerged as superseded incident evidence
Date: 2026-08-09
Decision owners: CWL security and CI maintainers

## Context

`sandboxed_verify.py` and `sandboxed_web_e2e.py` execute proof commands and publish completed output, timeout payloads, exceptions, backend/frontend service tails, command metadata, and structured result JSON. Applying redaction to only some print calls leaves credentials reachable through JSON, terminal/Unicode evasion, nested commands, explicit allowed environment values, or stream/result boundaries. Over-broad pattern matching can instead erase benign keys and the diagnostics needed to fix CI.

`ContextualWisdomLab/.github#841` identified the disclosure class but mixed an unrelated SSRF slice and missed publication paths. It was closed unmerged. Its first broad successor was also closed unmerged because secret-shaped fixtures remained in reachable history. [PR #888](https://github.com/ContextualWisdomLab/.github/pull/888) was the clean-history replacement, but a later committed credential-shaped fixture recontaminated its reachable history; it was closed unmerged and remains superseded incident evidence. Draft [PR #906](https://github.com/ContextualWisdomLab/.github/pull/906) is also closed unmerged `superseded`. [PR #1031](https://github.com/ContextualWisdomLab/.github/pull/1031) is the current open successor; do not merge overlapping [PR #929](https://github.com/ContextualWisdomLab/.github/pull/929) in parallel.

## Decision drivers

- Protect credentials across every CI/publication path.
- Preserve ordinary failure/timeout text, exit codes, commands after safe value substitution, and valid stable result JSON.
- Keep executed argv/environment/network/cleanup semantics unchanged.
- Resist JSON, ANSI, Unicode, multiline, nested-shell, and boundary-reassembly bypasses.
- Keep attacker-influenced processing bounded and near-linear.
- Avoid blanket PII masking and avoid corrupting benign diagnostic metadata.

## Alternatives considered

1. **Rely on GitHub's automatic secret masking.** Rejected because unknown, transformed, split, and child-generated values are not comprehensively covered.
2. **Redact only stdout/stderr at final print.** Rejected because timeouts, exceptions, service files/tails, commands, JSON, and pre-parser errors bypass it.
3. **Remove all logs or redact every `token`-like key.** Rejected because it destroys diagnosis and hides benign metrics such as token counts.
4. **One shared canonical redactor applied to complete content before truncation/serialization, with explicit allowed values and fail-closed preflight.** Selected.

## Decision

All human and structured evidence flows through `redact_sensitive_log.py`. It canonicalizes terminal/default-ignorable evasions, structurally handles supported JSON, recognizes credential semantics and exact explicit values, redacts complete service content before tail selection, sanitizes command/result metadata, separates publication boundaries, and preserves non-sensitive text/types/schema.

Explicit allowed environment values may be used only when they are long enough, single-line, printable, non-whitespace-only, non-control-bearing, non-marker-colliding, and not owned by the wrapper. Safe single-line values containing spaces remain eligible when exact-literal redaction and boundary tests pass. Unsafe values fail before execution without publishing colliding evidence. Setup/launch/parser errors are emitted only after a safe redaction context exists; otherwise the wrapper exits with the setup-failure code and no attacker-controlled output.

Credential redaction is not a total output quota and not a blanket PII masker. Resource limits and business-data access/retention remain separate controls.

## Consequences

Positive: a consistent, testable boundary closes asymmetric leaks while retaining useful diagnosis. Negative: redaction logic is security-critical and complex; unknown formats and raw on-disk service files remain residual risks; unsafe allowed values become a deliberate compatibility failure.

## Failure and recovery

If the redactor raises or cannot establish a safe context, fail closed before evidence publication, clean temporary state unless explicitly and safely retained, and return the documented setup code. If over-redaction breaks diagnosis, add a benign preservation fixture and narrow semantic classification without weakening exact secrets. If a live credential appeared, restrict evidence and rotate/revoke before source repair.

## Security and governance impact

This reduces credential disclosure and log-injection risk while preserving audit evidence. It does not grant permission to send private source/PII to an external model. Every new evidence sink must register with the boundary and threat model.

## Tests and acceptance

- completed/failure/timeout/exception output for both wrappers;
- backend/frontend full-log-before-tail behavior;
- JSON types/keys, multiline/escaped content, headers, cookies, private keys, JWT/provider tokens, URL userinfo;
- ANSI/backspace/cursor/default-ignorable and cross-stream/result reconstruction;
- separated and nested `sh -c`, `env`, `curl`, `sshpass`, MySQL, and Docker credential arguments;
- parser and temporary-workspace failures;
- single-line space-bearing allowed values plus rejection of short, whitespace-only, multiline/control, marker-colliding, and wrapper-owned values;
- stable exit code/result keys/valid JSON and ordinary diagnostic preservation;
- large hostile input and many explicit values within fixed performance budgets;
- 100% statement/branch/docstring evidence; and
- protected-main plus real consumer positive/negative proof.

## Migration and rollback

Integrate [PR #1031](https://github.com/ContextualWisdomLab/.github/pull/1031) through normal protection after current-head gates and qualifying review pass, then run a synthetic credential fixture from protected main and an affected consumer. Update the PR body, doctoring, and CHANGELOG with only final exact-head numbers. If regression requires rollback, disable the affected evidence publication or revert to a reviewed fail-closed no-output path; do not restore a known disclosure path.

## Supersession conditions

Supersede when the sandbox execution API provides typed, capability-safe evidence objects with built-in complete-boundary credential protection, bounded storage, diagnostic preservation, and equivalent adversarial proof.
