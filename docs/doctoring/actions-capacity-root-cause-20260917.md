# Doctoring record: the multi-hour review durations are inter-job global queue wait, not model/build time (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** `docs/ci-baseline-20260916.md` measured multi-hour p50/p95 durations for the long
  AI-review workflows (`opencode-review.yml` p50 8.4h/p95 12.9h, `strix.yml` p50 5.3h,
  `noema-review.yml` p50 5.3h, `.github` `opencode-review-dispatch.yml` p50 4.2h) and this task's
  original framing proposed capping concurrency for that job class. Maintainer steering asked for a
  per-step time breakdown before any capping: is the duration model API latency, retries/backoff,
  rate-limit waits, un-batched per-file/per-chunk calls, sleep/poll loops, repeated
  dependency installs/builds, or duplicated coverage/test execution? This record answers that with
  measured job-level timestamps from two completed runs of the workflow that does the actual heavy
  work (`opencode-review-dispatch.yml` in `.github` — see "Where the work actually happens" below).
- **Decision record:** [`docs/adr/0032-review-runner-occupancy-progress-bound.md`](../adr/0032-review-runner-occupancy-progress-bound.md)
  (Proposed) — bounds progress/admission occupancy, never model elapsed time; treats this
  measurement as proof that multi-hour wall time is inter-job queue wait under the ~60 plan
  ceiling. Whether a capacity-reservation concurrency cap is still needed remains an open
  follow-on; this record stays the measurement that decision must cite.

## Where the work actually happens

`opencode-review.yml` is the `pull_request_target`-triggered required-check entry point that runs
in each target repo's context. Its `coverage-source-tree` and `coverage-evidence` jobs are
deliberately no-op placeholders — each is a single `echo` step with no `needs:` edge between them —
whose inline comment already documents why: a real `needs:` edge between two jobs that declare no
`outputs:` only orders two context holders, and "under a saturated queue each link waits out the
whole queue again," citing a prior measurement on `naruon#1528` (run 33581213805) where that exact
pattern cost 22h41m of pure queueing for two single-echo jobs before it was fixed by depending both
directly on `admit-current-head` so they run in parallel. The actual coverage measurement and review
publication happen in `opencode-review-dispatch.yml` (`.github`, `repository_dispatch`-triggered),
which `opencode-review.yml` invokes. That workflow's job chain is
`validate-pr-metadata` → `coverage-source-tree` → `coverage-evidence` → `opencode-review-target`,
with real (not placeholder) `needs:` edges: `coverage-source-tree` uploads a
`opencode-coverage-source` tarball artifact that `coverage-evidence` downloads, and
`opencode-review-target` consumes `coverage-evidence`'s output.

## Measured evidence

Job-level `started_at`/`completed_at` timestamps, `repos/ContextualWisdomLab/.github/actions/runs/<id>/jobs`,
gathered 2026-09-17 for two completed runs of `OpenCode Review Dispatch` (workflow id `322670888`):

**Run 34931908846 (started 2026-09-15, during the saturated period this baseline documents):**

| Job | Started | Completed | Job duration | Wait since prior job completed |
|---|---|---|---|---|
| `validate-pr-metadata` | 17:44:59 | 17:45:04 | 5s | — |
| `coverage-source-tree` | 21:50:17 | 21:50:24 | 7s | 4h05m13s |
| `coverage-evidence` | 01:27:35 (+1d) | 01:28:47 | 1m12s | 3h37m11s |
| `opencode-review-target` | 07:23:03 | 07:42:31 | 19m28s | 5h54m16s |

Total wall time (first job start → last job completion): ~13h57m. Sum of actual job execution:
5s + 7s + 72s + 1168s ≈ **21 minutes (2.5% of wall time)**. Sum of inter-job queue wait:
**~13h36m (97.5% of wall time)**.

**Run 34756591400 (started 2026-09-13, lighter load) — the identical 4-job chain:**

| Job | Started | Completed | Wait since prior job completed |
|---|---|---|---|
| `validate-pr-metadata` | 12:22:15 | 12:22:20 | — |
| `coverage-source-tree` | 12:24:38 | 12:24:47 | 2m18s |
| `coverage-evidence` | 12:25:13 | 12:27:43 | 26s |
| `opencode-review-target` | 12:28:40 | 12:36:55 | 57s |

Total wall time: 14m40s, essentially all of it job execution. The workflow's own logic and step
content did not change between these two runs — the ~57x difference in total wall time (13h57m vs
14m40s) is explained entirely by how long each job waited to be admitted to a runner, which tracks
org-wide Actions saturation at the time, not anything the workflow does.

## What this rules out

- **Model API latency / retries / rate-limit waits:** the `opencode-review-target` job — which is
  where the actual model calls happen — took 19m28s and 8m15s respectively in the two sampled runs.
  Consistent with ordinary model-review work, not a multi-hour stall.
- **Sleep/poll loops waiting on another run:** none exist in `strix.yml`, `noema-review.yml`, or
  `opencode-review.yml`; `opencode-review-dispatch.yml`'s few `sleep 5`/`sleep 10` occurrences are
  bounded (≤120s) retry backoffs for transient `gh api` failures during head-fetch/publication, not
  busy-waits on another job or run. `opencode-review.yml`'s required job specifically forbids
  `sleep `/`while :; do`/`poll_interval_seconds` and is contract-tested to stay that way
  (`tests/test_opencode_required_rerun_capacity.py`); it wakes via a targeted
  `repository_dispatch` callback instead of polling.
- **Repeated, cacheable dependency installs/builds:** real, but already the subject of active fixes
  landed just before this session (`11a56305b` "build PyO3/maturin extensions offline before
  coverage", `efc35f72b` "vendor Cargo deps offline for the coverage sandbox") — and even fully
  un-cached, those builds run inside the `coverage-evidence` job, whose own execution time (72s and
  2m30s in the two samples) is a small fraction of the job's total wait.
- **Duplicated coverage/test execution:** `opencode-review.yml`'s own `coverage-source-tree`/
  `coverage-evidence` jobs do not re-run coverage; they are no-op placeholders that exist only to
  keep a stable required-check name in branch protection, per their own inline comment.

## What this confirms

The dominant cost is **inter-job wait for a fresh runner inside a single workflow run**, compounding
once per `needs:` edge, under the org's global concurrent-job ceiling
(`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`). `opencode-review.yml` already
applied the available fix for this (parallelize independent placeholder jobs instead of chaining
them) after discovering the identical pattern on `naruon#1528`. The same fix is **not available**
for `opencode-review-dispatch.yml`'s chain, because unlike the placeholder jobs, these three jobs
have a genuine data dependency (source tree → build artifact → review) *and* a deliberate,
already-documented trust boundary: `coverage-evidence` runs untrusted PR-head test/build code with
only `actions: read` permission (its own inline comment: "No repository-content, identity, secret,
or write token is available to untrusted tests"), isolated from `coverage-source-tree`'s
`id-token: write` app-token exchange and `opencode-review-target`'s broad write permissions
(`issues: write`, `pull-requests: write`, `statuses: write`, `security-events: read`). Merging these
jobs to remove queue-wait would let untrusted PR content execute in a process that recently held (or
will hold) elevated/write-capable tokens — a security regression this task's rules explicitly
forbid trading against speed. Reducing job count is therefore not an available lever for this
specific chain; the queue-wait can only be reduced by changing how many jobs of this class compete
for runners at once, which is what a capacity-reservation concurrency cap (if adopted) would target
directly, with this measurement as its justification rather than a bypassed diagnosis step.

## Bandscope re-trigger check (task item 3, partial)

Checked whether `bandscope`'s 89% required-workflow cancellation rate wastes runner-seconds (jobs
cancelled after starting) or is pure pre-admission churn (cancelled before a runner is ever
assigned). Sampled commit and check-suite timestamps on 5 open `bandscope` PRs via GraphQL: pushes
arrive in bursts (6–10 commits within 5–10 minutes, single author identity, consistent with this
org's documented shared agent-session identity actively iterating on a PR — not a bot loop or
webhook misfire) and the concurrency-group cancellation for the prior commit's check suites completes
within 1–3 seconds of the next commit's check suites being created — i.e. before any of those jobs
could plausibly have reached `in_progress`. The high cancellation rate is the existing
`cancel-in-progress` concurrency groups working as designed against a fast push cadence; it is not
evidence of wasted runner-slot time and does not, by itself, justify a workflow change. No further
action taken on item 3 in this record; still open whether the push cadence itself (many small commits
per PR in a short window) is worth addressing for reasons other than Actions capacity (e.g. review
noise), which is outside this task's scope.

## Audit trail

- `repos/ContextualWisdomLab/.github/actions/runs/34931908846/jobs` and
  `repos/ContextualWisdomLab/.github/actions/runs/34756591400/jobs` (REST, GitHub API, 2026-09-17).
- `.github/workflows/opencode-review.yml` lines ~290–319 (placeholder jobs and their inline
  queue-wait comment citing `naruon#1528` run 33581213805).
- `.github/workflows/opencode-review-dispatch.yml` `coverage-source-tree`/`coverage-evidence`/
  `opencode-review-target` job definitions and their `permissions:` blocks.
- `tests/test_opencode_required_rerun_capacity.py` (event-driven wake contract, no polling).
- Commits `11a56305b`, `efc35f72b` (offline build caching already landed).
- GraphQL `checkSuites`/commit timestamps on `ContextualWisdomLab/bandscope` PRs #1227, #1188,
  #1221, #1204, #1126 (2026-09-17).
- `docs/ci-baseline-20260916.md`, `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`,
  `docs/adr/0030-ci-centralization-scope-given-plan-ceiling.md`.
