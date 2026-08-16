# Inkspan hourly review-repair caller

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

## Decision and operating boundary

The central repository owns a thin scheduled caller for
`ContextualWisdomLab/inkspan`. It runs at minute 47 each hour and calls the
product-neutral `pr-review-fix-scheduler.yml` with protected base `main`, a
one-dispatch budget, and a one-hour same-head retry floor. Clearfolio runs at
minute 23 and DiskSage at minute 37, so the three callers do not create the same
avoidable runner burst.

The caller contains product identity, cadence, and explicit reusable-workflow
inputs only. Queue classification, exact-head binding, root-cause analysis,
remediation feasibility, retry markers, and repair dispatch remain central.
Inkspan continues to own its application, data, runtime, and release semantics.

## Authority and secret contract

The caller keeps `GITHUB_TOKEN` at `contents: read` and maps only
`PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN`. It never uses
`secrets: inherit`, receives `NVIDIA_NIM_API_KEY`, or introduces
`COPILOT_GITHUB_TOKEN`. CWE-269 forbids granting the caller the worker's
write or model privileges (MITRE, 2026). Model credentials remain scoped
to the separately reviewed repair worker. The worker cannot approve,
merge, release, change protection, or manufacture passing evidence.

Before protected-main activation, the repository variable
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain the exact
`ContextualWisdomLab/inkspan` target. Missing or mismatched configuration fails
before mutation credential materialization. GitHub App installation and both
mapped credentials must also remain limited to approved repositories.

## Failure and recovery

A missing target allowlist entry, credential, or exact-head evidence is a
non-passing configuration state. Operators correct the bounded configuration
and rerun the unchanged protected source; they do not widen a token, inherit all
secrets, bypass protection, or perturb a clean PR head merely to trigger review.
A newer heartbeat does not cancel an in-flight decision. Same-head retry
markers and the per-PR writer lease prevent duplicate repair writers.

After source integration, closure requires a scheduled or manual protected-main
consumer run that proves the exact Inkspan target, read-only caller token,
bounded dispatch decision, and fail-closed credential behavior. Source checks
alone are not protected-main operational acceptance. Merge also retains every
required security check, zero unresolved valid findings, and a qualifying
independent non-author approval.

## Verification and rollback

Machine-checkable contracts require the exact target, minute 47 cadence,
non-cancelling single-flight group, one dispatch, one-hour retry floor, explicit
secret mapping, read-only permissions, central path-filter coverage, and
absence of model or Copilot credentials. The full owned suite and hosted
security/review gates must pass on the unchanged exact head.

Rollback removes the Inkspan caller, its focused test, doctoring, and the
associated central path-filter/documentation entries. It must not remove the
reusable scheduler's dispatch validation or affect the independent Clearfolio
and DiskSage callers.

## APA 7th references

MITRE. (2026). *CWE-269: Improper privilege management*.
https://cwe.mitre.org/data/definitions/269.html

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 12, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August 12,
2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *Workflow syntax for GitHub Actions: Permissions*.
GitHub Docs. Retrieved August 12, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions
