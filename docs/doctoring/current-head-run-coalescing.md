# Current-head workflow-run coalescing

## Incident

On 2026-09-02, exact head `09908aaf56e568420105b81434c6cdd147856657` was reused when Draft pull request #1050 was closed and ready successor #1643 was opened. GitHub exposed two simultaneously queued runs for several expensive workflows on that unchanged branch/head, including Security Scan (`33561053485`, `33561076062`), CodeQL PR (`33561053137`, `33561076168`), Python Security (`33561053333`, `33561076150`), and SAST Semgrep (`33561053180`, `33561076360`). Equivalent duplicate pairs existed for Secret Scan, SBOM Generation, Scorecard PR, and OSV-Scanner PR.

The live-ref queue-hygiene repair from #1348 correctly prevents stale pull-request payloads from cancelling a newly pushed authoritative head. Its destructive revalidation intentionally preserves any run whose `head_sha` still equals the live branch ref. That safety invariant does not distinguish the sole authoritative current-head run from redundant queued siblings belonging to the same GitHub `workflow_id`. PR recreation therefore exposed a second, orthogonal capacity leak: safe stale-head preservation could retain several same-workflow runs for one current head.

## Trust boundary

`.github/workflows/current-head-run-coalescer.yml` executes only on `pull_request_target` `opened`, `synchronize`, and `reopened`. It checks out `ContextualWisdomLab/.github` at immutable `github.workflow_sha` with persisted credentials disabled. The job has only `actions: write`, `contents: read`, and `pull-requests: read`; it never checks out or executes the pull-request head.

The workflow passes the event's repository, PR number, head repository, head ref, and lowercase 40-character head SHA into `scripts/ci/current_head_run_coalescer.py`. The script immediately re-fetches the live PR before classification. Before every cancellation it re-fetches the candidate run, the live PR, and active runs for the exact head again. Missing, malformed, moved, closed, or ambiguous evidence preserves the candidate.

## Cancellation invariant

Runs are eligible only when all of the following are true:

1. the run was triggered by `pull_request` or `pull_request_target`;
2. its head repository, branch, and SHA exactly match the live open PR;
3. its stable numeric `workflow_id` matches another active exact-head sibling;
4. the candidate is still `queued` immediately before mutation; and
5. a distinct authoritative sibling is still active: either an `in_progress` sibling or a newer queued sibling.

The coalescer never selects an `in_progress` run. If a workflow already has an in-progress run, only queued siblings are redundant. If every matching run is queued, the greatest run ID is retained and older queued siblings are candidates. A candidate for which the authoritative sibling disappears is preserved. Cancellation uses GitHub's ordinary `/cancel` endpoint rather than `force-cancel`.

This invariant is deliberately separate from old-head cancellation. #1348 remains authoritative for resolving live Git refs before retiring superseded heads; the coalescer handles only redundant queued evidence on the same live head.

## Executable evidence

`tests/test_current_head_run_coalescer.py` pins the source and workflow contract. The regression was committed before either production file existed, so the initial expected failure was the absent coalescer implementation. The final cases cover one-run retention, in-progress preservation, isolation across workflow/head/branch/repository/event, sole-run preservation, moved-head/status fail-closed behavior, trusted-source checkout, PR-stable concurrency, and minimum workflow permissions.

A one-use read-only branch workflow was attempted solely to capture hosted RED/GREEN evidence; GitHub did not schedule newly introduced branch-only push workflows in this repository, so no hosted result is claimed from that mechanism and it was deleted from the publishable tree. Ordinary protected PR checks and independent review on the exact production head remain authoritative.

## Recovery and rollback

If the coalescer reports unexpected preservation, inspect the live PR/run/sibling identities before changing policy. Do not weaken the exact-head or authoritative-sibling checks to improve cancellation volume. If a false cancellation is ever observed, disable the `current-head-run-coalescer.yml` trigger first while retaining #1348 stale-head queue hygiene, then reproduce the identity race with a deterministic regression before repair.

The feature is operability-only: it does not convert cancelled, queued, missing, stale, or predecessor evidence into passing merge evidence, and it does not change required-check, security, review, or branch-protection policy.

## References

GitHub. (2026). *REST API endpoints for workflow runs*. GitHub Docs. https://docs.github.com/en/rest/actions/workflow-runs

GitHub. (2026). *Workflow syntax for GitHub Actions: concurrency*. GitHub Docs. https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#concurrency

National Institute of Standards and Technology. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5
