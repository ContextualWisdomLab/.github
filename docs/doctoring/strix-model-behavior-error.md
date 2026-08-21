# Strix ModelBehaviorError classifier

기준일: **2026-08-21**

## Incident

Required Strix scans can fail closed after the agent runtime raises
`ModelBehaviorError` even when the log reports `Vulnerabilities 0`. The
exception means the selected model did not follow Strix's tool-calling
protocol. Treating that protocol failure as a security finding blocked
current-head progress on otherwise empty scans.

## Decision

`scripts/ci/strix_quick_gate.sh` recognizes a **module-qualified**
`ModelBehaviorError` from `agents`, `pydantic_ai`, or `strix` as retryable
model evidence. A bare source-file mention is not enough. The gate moves to
the configured fallback sequence and does not retry the same model. The outer
`.github/workflows/strix.yml` neutralization path may skip only when that
signal is present **and** the log contains no vulnerability evidence.

`Vulnerabilities[[:space:]]+[1-9]` and `severity:` markers remain blocking.
Generic warnings, timeouts, provider failures, and MEDIUM-or-higher findings
are unchanged.

## Verification contract

`tests/test_strix_model_behavior_error.py` executes the production classifier
and the outer workflow neutralization condition against bounded synthetic
logs. It proves:

1. a module-qualified `agents`/`pydantic_ai`/`strix` `ModelBehaviorError`
   plus `Vulnerabilities 0` is retryable and may neutralize;
2. the same exception plus `Vulnerabilities 1` stays fail-closed;
3. lowercase application prose or a bare `ModelBehaviorError` token is not
   classified as the runtime exception;
4. the identifier is wired into infrastructure detection and cross-model
   fallback, never same-model retry.

## Rollback

If a future Strix release renames the exception, add the exact new identifier
and a matching regression. Do not remove the vulnerability fail-closed guard.

## References (APA 7th)

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved
August 21, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (n.d.). *Using workflow run logs*. GitHub Docs. Retrieved August 21,
2026, from https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs
