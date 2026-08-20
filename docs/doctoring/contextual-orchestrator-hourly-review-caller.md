# contextual-orchestrator hourly review-repair caller

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

## Decision and operating boundary

The central repository owns a thin scheduled caller for
`ContextualWisdomLab/contextual-orchestrator`, the LLM token-cost optimizer,
upstream load balancer, and routing hub. It runs at minute 17 each hour so it
does not share a runner burst with Clearfolio (23), DiskSage (37), or
fast-mlsirm (49). It calls the product-neutral `pr-review-fix-scheduler.yml`
with protected base `main`, a one-dispatch budget, and a one-hour same-head
retry floor.

The caller contains product identity, cadence, and explicit reusable-workflow
inputs only. Queue classification, exact-head binding, root-cause analysis,
remediation feasibility, retry markers, and repair dispatch remain central.
contextual-orchestrator continues to own routing, cost review, and release
semantics and remains independently operable as a standalone module.

## Authority and secret contract

The caller keeps `GITHUB_TOKEN` at `contents: read` and maps only
`PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN`. It deliberately does not
grant `id-token: write`: the established mapped scheduler credentials remain
the authority, while the optional OIDC exchange stays unavailable and
fail-closed. It never uses `secrets: inherit`, receives `NVIDIA_NIM_API_KEY`,
or introduces `COPILOT_GITHUB_TOKEN`. CWE-269 forbids granting the caller the
worker's write or model privileges (MITRE, 2026). Model credentials remain
scoped to the separately reviewed repair worker. The worker cannot approve,
merge, release, change protection, or manufacture passing evidence.

Before protected-main activation, the repository variable
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain the exact
`ContextualWisdomLab/contextual-orchestrator` target. Missing or mismatched
configuration fails before mutation credential materialization. GitHub App
installation and both mapped credentials must also remain limited to approved
repositories.

## Failure and recovery

A missing target allowlist entry, credential, or exact-head evidence is a
non-passing configuration state. Operators correct the bounded configuration
and rerun the unchanged protected source; they do not widen a token, inherit all
secrets, bypass protection, or perturb a clean PR head merely to trigger review.
A newer heartbeat does not cancel an in-flight decision. Same-head retry
markers and the per-PR writer lease prevent duplicate repair writers.

After source integration, closure requires a scheduled or manual protected-main
consumer run that proves the exact contextual-orchestrator target, read-only
caller token, bounded dispatch decision, and fail-closed credential behavior.
Source checks alone are not protected-main operational acceptance. Merge also
retains every required security check, zero unresolved valid findings, and a
qualifying independent non-author approval.

## Verification and rollback

Machine-checkable contracts require the exact target, minute 17 cadence,
non-cancelling single-flight group, one dispatch, one-hour retry floor, explicit
secret mapping, read-only permissions, central path-filter coverage, absence
of OIDC elevation, absence of model or Copilot credentials, and absence of
any target checkout or pull-request execution trigger. The full owned suite and
security/review gates must pass on the unchanged exact head.

Rollback removes the contextual-orchestrator caller, its focused test,
doctoring, and the associated central path-filter/documentation entries. It
must not remove the reusable scheduler's dispatch validation or affect the
independent Clearfolio, DiskSage, and fast-mlsirm callers.

## APA 7th references

MITRE. (2026). *CWE-269: Improper privilege management*.
https://cwe.mitre.org/data/definitions/269.html

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August 16,
2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *Workflow syntax for GitHub Actions: Permissions*.
GitHub Docs. Retrieved August 16, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions
