# GitHub Actions queue-health evidence

The scheduled `actions-queue-health.yml` workflow reads a fixed allowlist of
CWL repositories once per hour and publishes a JSON report plus a keyboard-
readable HTML report as an artifact. The collector uses only `gh api` reads
through the configured cross-repository `PR_REVIEW_MERGE_TOKEN` or
`OPENCODE_APPROVE_TOKEN`; it fails visibly when neither credential is present.
It does not cancel runs, mutate branches, dispatch workflows, or alter merge
gates, and it never relies on the central repository's scoped `GITHUB_TOKEN`
for sibling-repository reads.

The report schema is `actions.queue_health.v1`. Each observed run records its
repository, pull-request number, head SHA, event, run attempt, concurrency
group (or an explicit unavailable marker), queue age, job state, and runner
assignment. A run is `current_head` only when its linked open pull request and
head SHA match. Stale linked runs are `obsolete`; runs without a pull-request
link are `unlinked`. Queued evidence remains incomplete even when a report is
successfully produced.

Queued runs use run-level evidence because GitHub has not assigned their jobs;
only current-head `in_progress` runs make the additional jobs API read needed
to inspect a concrete runner assignment.

List endpoints use GitHub CLI pagination with at most 20 pages. Pull-request
and job lists use pages of 100 records; workflow-run lists use pages of 50 so a
large Actions queue does not require one oversized response. An incomplete,
malformed, or larger response fails closed instead of silently claiming that
the visible page is the whole queue.

Every external `gh api` read has a 30-second subprocess timeout, and the
collector job has a 30-minute execution ceiling. A timeout is typed as
incomplete queue evidence rather than success. Offline snapshots also reject
duplicate repository entries before counting runs so repeated input cannot
inflate the reported queue.

The default queue-age SLO is 900 seconds. A current-head job that remains
unassigned beyond that limit produces a warning and an explicit manual action
to inspect runner capacity, billing, runner-group policy, environment
approval, and concurrency saturation. The workflow intentionally remains
read-only and fail-closed when GitHub API or runner evidence is unavailable.
Paged API reads are not atomic; changing totals are retained only when the
collected records cover the largest observed total, and the report remains
explicitly an observation rather than a merge decision.

The allowlist is deliberately explicit in
`config/actions_queue_health_repositories.json`; adding a repository requires
review of its governance and data boundary. This first slice does not claim
that a queued run is obsolete or safe to cancel.
