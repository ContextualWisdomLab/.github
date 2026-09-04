# Current-head workflow-run coalescing

## Incident

On 2026-09-02 KST (2026-09-01 UTC), exact head `09908aaf56e568420105b81434c6cdd147856657` was reused when Draft pull request #1050 was closed and ready successor #1643 was opened. GitHub exposed two simultaneously queued runs for several expensive workflows on that unchanged branch/head, including Security Scan (`33561053485`, `33561076062`), CodeQL PR (`33561053137`, `33561076168`), Python Security (`33561053333`, `33561076150`), and SAST Semgrep (`33561053180`, `33561076360`). Equivalent duplicate pairs existed for Secret Scan, SBOM Generation, Scorecard PR, and OSV-Scanner PR.

The live-ref queue-hygiene repair from #1348 correctly prevents stale pull-request payloads from cancelling a newly pushed authoritative head. Its destructive revalidation intentionally preserves any run whose `head_sha` still equals the live branch ref. That safety invariant does not distinguish the sole authoritative current-head run from redundant queued siblings belonging to the same GitHub `workflow_id`. PR recreation therefore exposed a second, orthogonal capacity leak: safe stale-head preservation could retain several same-workflow runs for one current head.

## Trust boundary

`.github/workflows/current-head-run-coalescer.yml` executes on trusted `pull_request_target` events for `opened`, `synchronize`, `reopened`, `ready_for_review`, and `converted_to_draft`. It checks out `ContextualWisdomLab/.github` at immutable `github.workflow_sha` with persisted credentials disabled. The job has only `actions: write`, `contents: read`, and `pull-requests: read`; it never checks out or executes pull-request-head code. Event-derived repository/ref/SHA values are first placed in environment variables and are referenced from the shell only as quoted variables, so PR-controlled branch names are never interpolated directly into executable shell text.

The script re-fetches the live PR before classification. It lists all queued and in-progress repository runs rather than filtering only by workflow-run `head_sha`, because `pull_request_target` runs execute on the trusted base and their workflow head is not the PR head. Those runs are instead bound to the associated pull request's head identity. GitHub exposes repository identity in two different trusted REST shapes: the pull-request endpoint supplies a full repository object with `full_name`, while workflow-run `pull_requests[*].head.repo` and `base.repo` associations can contain only `id`, `name`, and canonical `https://api.github.com/repos/{owner}/{repo}` URL. `_repository_full_name()` therefore normalizes a valid full name directly or derives `owner/name` only from an exact HTTPS `api.github.com/repos/...` URL; malformed, query-bearing, foreign-host, non-HTTPS, or path-sentinel identities fail closed. This prevents a missing `full_name` field from turning every real workflow-run association into an empty repository identity while retaining a narrow authenticated GitHub boundary.

Before every cancellation the script re-fetches active same-head state, exact non-current PR associations, each possible same-workflow authoritative sibling, the current PR, and finally the candidate itself. Missing, malformed, moved, closed, completed, timed-out, or ambiguous evidence preserves the candidate or fails closed.

## Pull-request isolation

A workflow run may authorize cancellation only inside the current PR's evidence boundary. Runs associated with the current PR are eligible only when both their associated head and base match the current live PR exactly. A run associated with a different **open** PR never authorizes or receives cancellation, even when both PRs share the same branch and commit; those PRs retain independent required-check evidence. A run left behind by a **closed** predecessor may be coalesced into a successor only when both the run association and the predecessor's live record match the successor's exact head repository/ref/SHA **and exact base repository/ref/SHA**. A predecessor from an older base commit is therefore not interchangeable with the successor even when the base branch name is unchanged. This preserves the #1050-to-#1643 recreation repair only when the required-workflow evidence really represents the same merge boundary.

## Cancellation invariant

Runs are eligible only when all of the following are true:

1. the run was triggered by `pull_request` or `pull_request_target` and is bound to the current live PR head through the correct event-specific identity;
2. its PR association belongs either to the current PR or to a proven closed predecessor with the same exact head and exact base repository/ref/SHA identity;
3. its stable numeric `workflow_id` matches another run inside the same PR evidence boundary;
4. each candidate authoritative sibling identified from the bulk Actions snapshot is re-fetched by exact run ID and must still be queued or in progress with the same workflow/head/PR scope;
5. the current PR is re-fetched after sibling refresh and still exposes the same exact head/base boundary; and
6. the candidate is still `queued` on the final exact-run fetch immediately before mutation, while at least one refreshed distinct authoritative sibling remains active: either an `in_progress` sibling or a newer queued sibling.

The coalescer never selects an observed `in_progress` run. If a workflow already has an in-progress run, only queued siblings are redundant. If every matching run is queued, the greatest run ID is retained and older queued siblings are candidates. A candidate for which the authoritative sibling disappears, completes, changes identity, or becomes otherwise non-authoritative during refresh is preserved. Cancellation uses GitHub's ordinary `/cancel` endpoint rather than `force-cancel` and shares the same explicit `GH_TOKEN` and per-request timeout contract as every other API call.

GitHub's REST cancellation endpoint has no conditional `If-Status-Is-Queued` precondition and acknowledges cancellation asynchronously. Therefore no client can make the final GET and POST literally atomic. The implementation closes the controllable races by re-fetching the specific authoritative sibling(s), then the current PR, then performing the candidate GET last and requiring `queued` immediately before the ordinary cancellation POST. The regression suite covers both a candidate that changes from queued to in-progress and an authoritative sibling that becomes completed after the bulk snapshot; in both cases the candidate is preserved. The residual sub-request race after the final GETs is an upstream API limitation; the coalescer never uses force-cancel and does not claim stronger atomicity than the platform exposes.

This invariant is deliberately separate from old-head cancellation. #1348 remains authoritative for resolving live Git refs before retiring superseded heads; the coalescer handles only redundant active evidence for one live PR head.

## Executable evidence

`tests/test_current_head_run_coalescer.py` and `tests/test_current_head_run_coalescer_review_regressions.py` pin the source and workflow contract. Coverage includes one-run retention, in-progress preservation, `pull_request_target` base/head separation, real minimal Actions repository-association normalization for both PR event families, fail-closed repository URL normalization, isolation between concurrently open PRs, exact-base isolation across closed predecessor succession, same-workflow sibling re-fetch, completed-sibling preservation, workflow/head/branch/repository/event isolation, moved-head/status fail-closed behavior, per-call timeouts, explicit cancellation authentication, complete pagination, final candidate re-fetch, ready/draft transition triggers, trusted-source checkout, shell-injection resistance, PR-stable concurrency, and minimum workflow permissions.

The minimal-repository-shape regression was committed before the production normalization repair. On the pre-fix source `_head_tuple()` read only `repo.full_name`, so the real Actions fixture deterministically normalized to an empty repository string. Production now accepts the fuller pull-request representation and the minimal workflow-run representation through the same bounded owner/name normalization contract.

A one-use read-only branch workflow was attempted solely to capture hosted RED/GREEN evidence; GitHub did not schedule newly introduced branch-only push workflows in this repository, so no hosted result is claimed from that mechanism and it was deleted from the publishable tree. Ordinary protected PR checks and independent review on the exact production head remain authoritative.

## Recovery and rollback

If the coalescer reports unexpected preservation, inspect the live PR/run/sibling identities before changing policy. Do not weaken repository normalization, exact-head, exact-base, PR-association, final-status, refreshed-sibling, or authoritative-sibling checks to improve cancellation volume. If a false cancellation is ever observed, disable the `current-head-run-coalescer.yml` trigger first while retaining #1348 stale-head queue hygiene, then reproduce the identity race with a deterministic regression before repair.

The feature is operability-only: it does not convert cancelled, queued, missing, stale, or predecessor evidence into passing merge evidence, and it does not change required-check, security, review, or branch-protection policy.

## References

GitHub. (2026). *REST API endpoints for workflow runs*. GitHub Docs. https://docs.github.com/en/rest/actions/workflow-runs

GitHub. (2026). *Workflow syntax for GitHub Actions: concurrency*. GitHub Docs. https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#concurrency

National Institute of Standards and Technology. (2020). *Security and privacy controls for information systems and organizations* (NIST Special Publication 800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5
