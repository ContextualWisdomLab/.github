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

## Alternatives

- Leaving the queue intact was rejected because Draft is an explicit admission
  withdrawal and stale queued work consumes the organization job ceiling.
- Cancelling runs from the repair client was rejected because it duplicates the
  canonical workflow owner and depends on a privileged external sweeper.
- Adding a new cancellation job was rejected because workflow-level concurrency
  already performs the exact same-head retirement before runner admission.

## Verification

`test_converted_to_draft_retires_queued_run_without_runner` first failed for
all affected workflows because the event was absent. The later single-writer
reconciliation first produced two focused failures against CodeQL's blanket
Draft guard, then passed the combined Draft materialization and retirement
matrix. An affected-workflow audit also found and corrected one stale SAST
test oracle that still required the old closed-only job guard. On the refreshed
two-parent integration tree, the focused Draft-control and queue suite reports
86 passes and the warnings-fatal repository suite reports 5,273 passes with
five optional skips. Hosted exact-head checks remain required before protected
merge.

## Follow-up

After ordinary protected merge, observe the next Draft transition and confirm
that the older CodeQL PR, SAST Semgrep, Security Scan, and Python Security runs
leave the queue without assigning a hosted or control runner.
