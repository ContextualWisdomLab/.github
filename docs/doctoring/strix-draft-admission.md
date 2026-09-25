# Strix Draft pull-request admission

## Decision

`.github/workflows/strix.yml` now evaluates Draft state at job level for
`pull_request_target` events. Draft `opened`, `synchronize`, and `reopened`
generations skip both metadata jobs, so the dependent `strix` job is skipped
without a runner. `ready_for_review` remains in the trigger types and carries
`draft == false`, so it admits a fresh exact-head metadata generation and then
the real scan. Non-PR `push`, `schedule`, and `repository_dispatch` events
remain admitted.

`converted_to_draft` remains a trigger event so workflow-level
`cancel-in-progress` retires an older Ready generation. Its replacement is
runner-free: the explicit API cleanup job is not admitted for that event.
Closed PRs and non-Draft synchronize events retain the existing cleanup path,
including its live-target and superseded-run checks.

This preserves the required `strix` check shape for non-Draft PRs and forced
repository-dispatch scans. A Draft run produces skipped job conclusions rather
than leaving an uncreated trigger-level check Pending; Draft PRs cannot merge,
and the Ready transition creates the exact-head scan that can satisfy the
required context.

## Timeout decision

The `strix` job still has no job-level `timeout-minutes`. This was verified
against the workflow and the existing timeout contracts. The job runs the
model synchronously and explicitly sets `LLM_TIMEOUT`,
`STRIX_MEMORY_COMPRESSOR_TIMEOUT`, `STRIX_PROCESS_TIMEOUT_SECONDS`, and
`STRIX_TOTAL_TIMEOUT_SECONDS` to zero. The repository's standing model-path
policy accepts central Strix work taking more than two hours and rejects
elapsed inference caps; the active Strix occupancy record therefore uses
progress-based transport release rather than a wall-clock job deadline.

Adding a job timeout here would terminate legitimate large-repository analysis
and contradict that policy. The short job-level limits on `changed-scope`,
`admit-current-head`, and the superseded-run cleanup remain because those jobs
perform bounded metadata/API work, not model inference.

## Scope and follow-up

This repair changes only Strix Draft admission and documents the timeout
decision. The other heavy required PR workflows should receive the same
runner-free Draft/`ready_for_review` lifecycle treatment in a separate,
coordinated change: Security Scan, SAST Semgrep, CodeQL PR, Python Security,
and Agent Review Runtime Quality. No metadata-job consolidation is included;
that remains a separate queue-reduction concern.
