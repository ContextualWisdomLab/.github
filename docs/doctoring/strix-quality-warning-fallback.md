# Strix model-quality warning fallback

검토 기준일: **2026-08-21**

## Incident

The central Strix workflow selected the public-repository NVIDIA NIM model
`nvidia/nemotron-3-super-120b-a12b`. Strix completed a scan and produced only a
`LOW` finding, but it also emitted `MODEL QUALITY WARNING` because the selected
model was not a recommended frontier model. The gate correctly classified the
warning as non-clean evidence, then stopped before trying the configured
fallback models. This left an actionable low-severity report indistinguishable
from an unrecoverable provider failure and blocked the target pull request.

## Decision

`scripts/ci/strix_quick_gate.sh` recognizes only Strix's exact model-quality
warning (`MODEL QUALITY WARNING` / `is not a recommended frontier model for
Strix`) as retryable model evidence. It remains an infrastructure/failure
signal, so the scan never passes merely because the warning was seen. The
existing fallback sequence must obtain a clean result or the gate fails closed.

All other `Warn`, `Warning`, `Fatal`, `Denied`, and `Timeout` output remains a
hard failure. A `MEDIUM` or higher vulnerability remains blocking even when a
fallback succeeds; below-threshold findings are handled by the existing
`STRIX_FAIL_ON_MIN_SEVERITY` policy.

## Verification contract

`tests/test_strix_nvidia_nim_not_found_fallback.py` executes the production
classifier against a bounded quality-warning log and asserts that the warning
is wired into `is_model_retryable_error`. The existing shell harness continues
to cover generic warning signals and fallback failure paths.

## Rollback

If a future Strix release changes the warning wording, add the exact new
provider-produced wording to the narrow classifier and its regression test.
Do not remove generic warning failure handling or neutralize the entire warning
class.

## References (APA 7th)

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved
August 21, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (n.d.). *Using workflow run logs*. GitHub Docs. Retrieved August 21,
2026, from https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs
