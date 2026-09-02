# Closed central review-dispatch retirement

## Incident

On 2026-09-02 the central Actions queue still contained OpenCode review run
`33574321895`, titled
`OpenCode Review Dispatch ContextualWisdomLab/contextual-orchestrator#946@4b402cdae00289abce52b68ee33942fd4ba69ae5`.
The target PR was already closed and merged. The central workflow itself would
reject the closed PR after it obtained a runner, but until then the queued run
still consumed shared Actions capacity.

The existing current-head scheduler cancellation is correct for open PRs: it
recognizes central `repository_dispatch` run titles, keeps the exact live head,
and force-cancels older heads. The missing lifecycle transition was closure.
Once a target PR disappears from the open-PR sweep, no later target event is
available inside the central `.github` repository to cancel the already queued
privileged dispatch.

## Repair

`central-review-dispatch-reaper.yml` runs only from the trusted central default
branch. It reads active central `repository_dispatch` runs and delegates exact
classification to `scripts/ci/closed_review_dispatch_reaper.py`.

A run is mutable only when all of the following are true:

1. its workflow name is one of the bounded central OpenCode, Noema, or Strix
   review workflows;
2. its run title exactly encodes a `ContextualWisdomLab/<repository>#<PR>@<40
   hex SHA>` identity;
3. live target PR metadata is successfully re-read; and
4. the PR is closed, or the PR remains open but its live head differs from the
   dispatched head.

The exact current open head is always preserved. Malformed titles, unknown
workflows, unavailable target metadata, non-`repository_dispatch` runs, and
runs that cannot be proven stale are not cancelled.

## Trust and permissions

The workflow has only `actions: write`, `contents: read`, and `id-token: write`.
It checks out `ContextualWisdomLab/.github` at `github.workflow_sha` with
credentials disabled and never checks out target PR source. `github.token` is
used only for Actions mutation in the central repository. Target metadata reads
use the existing OpenCode App exchange when available, with the established
scheduler read-token fallbacks. Secret values are masked and are never included
in diagnostics.

The hourly workflow uses a single stable concurrency group with
`cancel-in-progress: true`, so at most the newest reaper attempt consumes
capacity. The reaper complements, rather than replaces, per-PR concurrency and
the event-driven stale-head cancellation paths.

## Regression evidence

`tests/test_closed_review_dispatch_reaper.py` was committed before the
implementation. It failed because the reaper source and workflow did not yet
exist. The local RED reproduction then became GREEN with six classifier/safety
cases, and the repository regression additionally binds the trusted checkout,
minimal Actions write authority, and absence of PR-triggered privileged source
execution.

The durable acceptance property is not a green status for a cancelled run. It
is that proven closed-target and previous-head central review runs stop consuming
capacity while the sole exact-current-head authoritative run is never cancelled.
