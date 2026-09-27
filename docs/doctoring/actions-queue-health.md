# GitHub Actions queue-health evidence

The scheduled `actions-queue-health.yml` workflow reads a fixed allowlist of
CWL repositories once per hour and publishes a JSON report plus a keyboard-
readable HTML report as an artifact. It mints a short-lived, Actions-read and
pull-request-read `cwl-noema-review` installation token scoped to the reviewed
allowlist. The existing cross-repository `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN` remain fallbacks; all collector calls are `gh api` reads.
It does not cancel runs, mutate branches, dispatch workflows, or alter merge
gates, and it never relies on the central repository's scoped `GITHUB_TOKEN`
for sibling-repository reads.

On 2026-09-24, scheduled run `35983954568` reached a hosted runner but had an
empty `GH_TOKEN`: neither named cross-repository secret was available to the
workflow. The organization already has an all-repository `cwl-noema-review`
installation with Actions-read access and the matching private key/client ID.
The workflow now scopes a temporary read-only token to its reviewed allowlist.
If minting and both fallbacks are unavailable, it writes a fail-closed JSON/HTML
artifact listing every allowlisted repository as uncollected and naming the
credential action; the job still fails. The 2026-09-24 run proves missing
credentials in that workflow, not the cause of the wider queue.
Any repository collection error also leaves the artifact but fails the job,
so a partial census cannot appear as successful monitoring.

The report schema is `actions.queue_health.v1`. Each observed run records its
repository, pull-request number, head SHA, event, run attempt, concurrency
group (or an explicit unavailable marker), stable workflow identity, queue age,
job state, and runner assignment. When GitHub supplies a positive
`workflow_id`, the report exposes `workflow_identity` as `workflow_id:<id>` and
uses that value for duplicate-lane grouping; `workflow_name` remains
presentation data. Older/offline v1 snapshots that lack `workflow_id` retain a
compatibility fallback of `workflow_name:<name>`. A malformed present
`workflow_id` fails closed instead of being coerced.

A run is `current_head` only when its linked open pull request and reviewed
head SHA match. For `pull_request`, the run-level `head_sha` identifies the
immutable generation. A live 2026-09-27 census found 17 superseded runs whose
`pull_requests[].head.sha` had already changed to the current PR head; that
mutable link must not turn an older run into current evidence.
For `pull_request_target`, the run-level head is the trusted base and must
never be compared directly with the PR head; its existing linked-head handling
remains a limitation requiring independent event/run-name provenance before
operational cancellation. `repository_dispatch` runs without PR links remain
`unlinked`; this slice does not infer their target from the control-plane head.
Stale linked runs are `obsolete`. Queued evidence remains incomplete even when
a report is successfully produced. GitHub's `waiting` job status also remains
pending evidence, distinct from a runner-capacity blocker.

Pull-request identity is sampled before and after the bounded active-run
sweeps. The repository snapshot is accepted only when the open pull-request
number/state/head view is unchanged. A push, closure, or other identity change
between those samples becomes repository-scoped incomplete evidence instead of
being allowed to invert current/obsolete classification. A pull-request
response with incomplete head/base identity retains one bounded retry after a
one-second delay.

Queue age for a fetched job is measured from that job's own `created_at`, not
the parent run's, so a later job in an already in-progress run (for example one
gated by `needs:`) that only just became eligible is not measured against the
whole run's age and does not trigger a false capacity-breach alert. Every row
exports both `queue_age_started_at` and `queue_age_source` (`job_created_at` or
`run_created_at`) so consumers can reproduce the reported `queue_age_seconds`.
Requested, pending, and queued runs intentionally use run-level evidence when
GitHub has not supplied job detail.

Two bounded active-status sweeps run in opposite orders and must agree before
the snapshot is accepted. This prevents historical completed runs from
exhausting the bound while rejecting evidence that changes between partitioned
reads. Each status read uses up to 20 pages of 50 runs, reusing the existing
list-pagination bound. This covers an observed queue of more than 600 runs
without truncating it at the first page. Exceeding the bound, duplicate page
identities, and incomplete pagination still produce incomplete evidence. Current-head `in_progress` and `waiting` runs make the additional jobs
API read needed to distinguish concrete runner assignment from an environment
or deployment approval wait.

List endpoints use collector-controlled GitHub API pagination with at most 20
explicit page reads; the collector never asks GitHub CLI to download an
unbounded page set and never requests page 21. Pull-request and job lists use
pages of 100 records; workflow-run lists use pages of 50 so a large Actions
queue does not require one oversized response. An incomplete, malformed, or
larger response is recorded as repository-scoped incomplete evidence and the
collector continues with the remaining allowlisted repositories; it never
silently claims that the visible page is the whole queue. The JSON and HTML
reports expose each collection error explicitly.

Independent job-evidence reads use at most four worker threads per repository.
Every selected run is still inspected; concurrency does not reduce the evidence
set or change the page limits. Report rows remain sorted by run ID, and the
final pull-request identity read happens after all job reads finish. A failed
job read invalidates the repository snapshot exactly as a sequential failure
does. Model calls and their execution budgets are unaffected.

Every external `gh api` read has a 30-second subprocess timeout, and the
collector job has a 30-minute execution ceiling. A timeout is typed as
incomplete queue evidence rather than success. Repository names reject `.` and
`..` path segments. Offline snapshots also reject duplicate repository entries
before counting runs so repeated input cannot inflate the reported queue.

The default queue-age SLO is 900 seconds. A current-head job that remains
unassigned beyond that limit produces a warning and an explicit manual action
to inspect runner capacity, billing, runner-group policy, environment approval,
and concurrency saturation. The workflow intentionally remains read-only and
fail-closed when GitHub API or runner evidence is unavailable. Paged API reads
are not atomic; changing totals are retained only when the collected records
cover the largest observed total, and the report remains explicitly an
observation rather than a merge decision.

Implementation ownership is intentionally split without duplicate collector
copies: `actions_queue_health_core.py` owns the shared bounded parsing and
reporting primitives, while the executable `actions_queue_health.py` entrypoint
owns stable pull/workflow identity and audit-provenance reconciliation. Tests
load the executable boundary used by the scheduled workflow.

The allowlist is deliberately explicit in
`config/actions_queue_health_repositories.json`; adding a repository requires
review of its governance and data boundary. This first slice does not claim
that a queued run is obsolete or safe to cancel.

## References

GitHub. (n.d.). *REST API endpoints for workflow runs*. Retrieved August 20,
2026, from https://docs.github.com/en/rest/actions/workflow-runs

Internet Engineering Task Force. (2022). *HTTP semantics* (RFC 9110).
https://www.rfc-editor.org/rfc/rfc9110

OWASP Foundation. (n.d.). *Path traversal*. Retrieved August 20, 2026, from
https://owasp.org/www-community/attacks/Path_Traversal
