# Heavy pull-request workflow Draft admission

## Decision

The first runner-consuming job in each of these pull-request workflows now
requires a non-Draft pull request:

- `security-scan.yml`: `changed-scope`
- `sast-semgrep.yml`: `semgrep`
- `codeql-pr.yml`: `detect-languages`
- `python-security.yml`: `detect-python`
- `agent-review-runtime-quality-ci.yml`: `agent_review_runtime_quality`

The PR triggers retain `ready_for_review` and now also subscribe to
`converted_to_draft`. A Draft `opened`, `synchronize`, or `reopened` event
therefore produces skipped job conclusions without admitting a runner. A
`ready_for_review` event has `draft == false` and creates a fresh generation.
The Draft conversion generation remains runner-free while each workflow's
repository-and-PR `cancel-in-progress: true` concurrency group retires the
previous Ready generation. Closed events remain subscribed where needed so
workflow cancellation still retires superseded work.

Mixed-event workflows use a non-PR bypass in their job condition. Push,
schedule, and `repository_dispatch` scans in SAST Semgrep and Python Security
therefore remain unchanged. Security Scan, CodeQL PR, and Runtime Quality are
pull-request workflows, so their new condition is PR-specific by construction.

CodeQL gates `detect-languages`, not the matrix-consuming `analyze-head` job.
The existing matrix safety boundary remains intact: `analyze-head` has no
needs-output-dependent job-level condition, avoiding literal unexpanded
matrix check names. When language detection is skipped for a Draft, downstream
analysis is skipped through its existing dependency.

Every changed workflow still has a job-level conclusion for the lifecycle run;
no trigger-level Draft filter was introduced. Required contexts therefore
receive skipped conclusions rather than being left Pending by an absent
workflow invocation.

## Scope

This change does not alter exact-head checkout or admission logic, scanner
steps, concurrency keys, non-PR triggers, timeout budgets, or metadata-job
consolidation. The Agent Review Runtime Quality path filters and `main` base
branch restriction remain unchanged.
