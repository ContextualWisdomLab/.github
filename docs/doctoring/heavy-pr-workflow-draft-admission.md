# Heavy pull-request workflow Draft admission

## Decision

The first runner-consuming job in each of these pull-request workflows now
has a Draft lifecycle guard:

- Native `.github` runs: `security-scan.yml` (`changed-scope`), SAST
  Semgrep (`semgrep`), and CodeQL PR (`detect-languages`) require a
  non-Draft pull request.
- Direct-run-only workflows: Python Security (`detect-python`) and Agent
  Review Runtime Quality (`agent_review_runtime_quality`) retain their
  non-Draft guards without a repository bypass.

The PR triggers retain `ready_for_review` and now also subscribe to
`converted_to_draft`. A Draft `opened`, `synchronize`, or `reopened` event
in native `.github` runs therefore produces skipped job conclusions without
admitting a runner. A native `ready_for_review` event has `draft == false` and
creates a fresh generation. Ruleset-launched Security Scan, SAST, and CodeQL
runs bypass the Draft condition because their ignored `types` filter does not
re-trigger them on `ready_for_review`. The Draft conversion generation
remains runner-free while each workflow's
repository-and-PR `cancel-in-progress: true` concurrency group retires the
previous Ready generation. Closed events remain subscribed where needed so
workflow cancellation still retires superseded work.

Mixed-event workflows use a non-PR bypass in their job condition. Push,
schedule, and `repository_dispatch` scans in SAST Semgrep and Python Security
therefore remain unchanged. Security Scan and CodeQL PR use the repository
bypass because they are ruleset-required; Runtime Quality remains direct-run
only and keeps its existing branch/path filters.

CodeQL gates `detect-languages`, not the matrix-consuming `analyze-head` job.
The existing matrix safety boundary remains intact: `analyze-head` has no
needs-output-dependent job-level condition, avoiding literal unexpanded
matrix check names. When language detection is skipped for a Draft, downstream
analysis is skipped through its existing dependency.

Every changed workflow still has a job-level conclusion for the lifecycle run;
no trigger-level Draft filter was introduced. Native `.github` Draft runs
receive skipped conclusions, while ruleset-targeted required contexts remain
admitted and continue to produce security evidence.

## Scope

This change does not alter exact-head checkout or admission logic, scanner
steps, concurrency keys, non-PR triggers, timeout budgets, or metadata-job
consolidation. The Agent Review Runtime Quality path filters and `main` base
branch restriction remain unchanged.
