# Draft-transition queue retirement

## Incident

A live organization sample on 2026-09-30 found 100 of the 100 most recently
updated Open Ready pull requests with required workflows still queued. Twenty-five
of those pull requests had a terminal workflow failure, a current
`CHANGES_REQUESTED` review, an unresolved review thread, or an explicit
predecessor/partial-implementation boundary and were moved back to Draft at
their unchanged exact heads.

The central CodeQL PR, SAST Semgrep, Security Scan, and Python Security
workflows already used per-PR `cancel-in-progress: true` concurrency. They
subscribed to `ready_for_review` but not `converted_to_draft`. Consequently,
a Draft transition could stop future product admission but could not create the
same-concurrency replacement run that retires the already queued Ready event.

A second live sample on 2026-10-01 exposed a distinct central-dispatch gap.
The `.github` receiver held 457 queued and two in-progress
`repository_dispatch` runs. Of the newest 100 queued runs, 38 targeted a
superseded PR head and five targeted an already closed PR; 20 of those stale
runs were CodeQL and 18 were OpenCode. Workflow concurrency only coalesces a
new run in the same group. A Draft transition or PR closure that creates no new
central dispatch therefore leaves the old run queued. The scheduler made this
worse by returning `draft PR` before stale-run cleanup, and closed PRs never
entered its open-PR loop at all.

## Decision

Each affected workflow subscribes to `converted_to_draft`. Ordinary entry jobs
require a non-Draft pull request, while CodeQL uses the narrower explicit
repository/event matrix in
[`codeql-draft-ready-materialization.md`](codeql-draft-ready-materialization.md):
consumer Draft heads scan, native-owner Draft heads do not, and
`converted_to_draft` never starts a replacement scan. GitHub therefore applies
workflow-level concurrency and cancels the older same-PR run, then skips the
replacement before assigning a runner.

The concurrency key, permissions, checkout identity, scanner configuration,
failure threshold, and Ready-head behavior remain unchanged. No workflow run is
rerun manually, no required result is synthesized, and no failed result is
converted to success.

The scheduler now performs a bounded central-dispatch retirement sweep for the
known protected CodeQL, OpenCode, and Strix workflow paths. It accepts only the
exact repository/PR/head identity encoded in those workflows' `run-name`, then
re-fetches the active run and target PR immediately before cancellation. It
covers all five GitHub active states (`queued`, `in_progress`, `waiting`,
`pending`, and `requested`) so a state transition cannot escape retirement. It
cancels only a run whose target PR is closed or whose encoded head differs from
the freshly fetched live head. Current-head and malformed runs are preserved;
authority-read failures fail closed. A consumer event performs central
retirement only when an explicit organization Actions token is configured;
its repository-scoped token is never treated as central authority. Draft PRs
run this cleanup before the
ordinary Draft skip. The scheduler's existing `pull_request_target` receiver
admits only `converted_to_draft` and `closed` transition events to its bounded
control job; a closed PR is cleaned and returned before any review, branch,
auto-merge, or merge path can run. Ordinary Draft events still assign no
runner.

## Alternatives

- Leaving the queue intact was rejected because Draft is an explicit admission
  withdrawal and stale queued work consumes the organization job ceiling.
- An unbounded external cancellation client was rejected. The selected repair
  remains in the canonical `.github` scheduler owner, recognizes only protected
  central workflow identities, and revalidates exact run and PR authority at
  the destructive boundary.
- Adding a new cancellation job was rejected because workflow-level concurrency
  already performs the exact same-head retirement before runner admission.

## Verification

`test_converted_to_draft_retires_queued_run_without_runner` first failed for
all affected workflows because the event was absent. The later single-writer
reconciliation first produced two focused failures against CodeQL's blanket
Draft guard, then passed the combined Draft materialization and retirement
matrix. An affected-workflow audit also found and corrected one stale SAST
test oracle that still required the old closed-only job guard. The resulting
workflow-consumer suite reports 672 passes, and the warnings-fatal repository
suite reports 5,259 passes, five optional-platform skips, and 40 subtests.
Hosted exact-head checks remain required before protected merge.

The later central-dispatch RED suite reproduced three failures: Draft returned
before cleanup, no CodeQL central cleanup API existed, and closed-PR runs had no
fresh-authority path. The implementation passes all 458 focused scheduler and
admission tests with warnings treated as errors, including stale/current/closed,
malformed identity, authority outage, five-state transitions, Draft ordering, and transition-event
cleanup-only coverage. This is local evidence only; hosted exact-head checks and
independent review remain required.

## Follow-up

After ordinary protected merge, observe the next Draft transition and PR
closure. Confirm that older direct runs retire through workflow concurrency and
that stale/closed CodeQL, OpenCode, and Strix central dispatches are cancelled
without touching current-head runs or assigning a CodeQL, OpenCode, or Strix
worker merely to reject stale identity. The bounded scheduler control job is
expected only for the Draft/close transition that performs the retirement.
