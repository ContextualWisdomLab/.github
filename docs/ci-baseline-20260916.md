# CI baseline — 2026-09-16

Measurement window: last 24h ending 2026-09-16T12:57:58Z, all 79 non-archived
`ContextualWisdomLab` repositories, via `GET /repos/{owner}/{repo}/actions/runs?created=>=<since>`
(REST, one repo at a time; GraphQL used only for the repo list). Raw run rows: 9,353
across 400 (repo, workflow, event) groups. Full per-group detail: `ci-baseline-20260916.csv`.

## Headline numbers (org-wide, run level)

| Metric | Value |
|---|---|
| Runs in 24h | 9,353 |
| Cancelled/superseded | 4,000 (42.8%) |
| Run-level queue time (`created_at` → `run_started_at`), p50 / p95 | 0.0s / 0.0s |
| Run-level queue time, max observed | 74,723s (~20.8h), `.github` `codeql-pr.yml` |
| Distinct (repo, workflow, trigger) groups | 400 |

**The run-level queue KPI is not the right signal here — read the note below before using it.**
`run_started_at` flips to non-null as soon as *any* job in the run leaves the queue, so a run with
one fast job and ten stuck jobs still reports ~0s queue time. This is why p50/p95 are 0.0s for
almost every group in the CSV even on repos with visibly stuck checks.

## The real symptom: job/check-suite level queuing, confirmed live

Live GraphQL check-suite query against `fast-mlsirm`'s 5 most recently updated open PRs
(2026-09-16, same session):

| PR | Rollup state | GitHub Actions check suites, all `QUEUED` |
|---|---|---|
| #1886 | SUCCESS | 0 (only non-GH-Actions app suites, which stay QUEUED indefinitely and are not CI) |
| #1885 | SUCCESS | 0 |
| #1882 | PENDING | 11 |
| #1883 | PENDING | 11 |
| #1884 | PENDING | 11 |

Newer PR heads (#1885, #1886) completed; older heads (#1882–#1884) sit with all 11
GitHub-Actions-run check suites permanently `QUEUED`. That head-of-line pattern — a few heads
running, many stuck — reproduces exactly the signature already on record in
[`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`](doctoring/actions-plan-concurrency-ceiling-20260903.md):
single-digit `in_progress` against triple/quadruple-digit `queued`, org-wide. Re-checked live in this
session:

| Repo | `in_progress` | `queued` |
|---|---|---|
| `fast-mlsirm` | 8 | 220 |
| `.github` | 6 | 220 |
| `bandscope` | 0 | 73 |
| `naruon` | 0 | 67 |

That doctoring record's conclusion, dated 2026-09-03 and still consistent with this session's
2026-09-16 numbers: the primary bottleneck is a **plan-level concurrent-job ceiling** (user-reported
58-60/60 concurrent jobs in use at the time), not per-repo or per-workflow-file duplication. It
explicitly warns that a large cross-repo workflow-consolidation effort "would be solving the wrong
layer of the problem." This baseline does not contradict that finding — it corroborates it two weeks
later with the same queued≫in_progress shape.

## Duration (`run_started_at` → completion), heaviest groups

Excerpt (see CSV for all 400 rows). These durations mostly reflect **policy-accepted long model-review
runs** (see `docs/product-goal-directive.md` §8: OpenCode/Strix/Noema may legitimately run 2+ hours;
`#1889`/`#1890`/`#1892` timeout attempts were reverted on this evidence), not stalls:

| Repo | Workflow | Trigger | Runs | Cancelled | Duration p50 | Duration p95 |
|---|---|---|---|---|---|---|
| fast-mlsirm | opencode-review.yml | pull_request_target | 68 | 21 (31%) | 8.4h | 12.9h |
| fast-mlsirm | strix.yml | pull_request_target | 68 | 20 (29%) | 5.3h | 11.4h |
| fast-mlsirm | noema-review.yml | pull_request_target | 68 | 20 (29%) | 5.3h | 8.8h |
| bandscope | strix.yml | pull_request_target | 91 | 81 (89%) | 78s | 4.6h |
| `.github` | opencode-review-dispatch.yml | repository_dispatch | 137 | 4 (3%) | 4.2h | 17.8h |

`bandscope`'s 89% cancellation rate on `strix.yml` (and similarly high on its other 6 required
workflows, all pinned at 91 runs / ~80 cancelled) stands out as the one clear duplication/thrash
signal in this dataset: nearly every PR push on that repo cancels and re-triggers all 7 of its
required workflows, which is exactly the per-push-supersession pattern centralized concurrency
groups are meant to absorb — worth a follow-up look at what is re-triggering so often there.

## Scheduled/hourly workflows per repo (event = `schedule`)

22 repos run at least one scheduled workflow in the 24h window; `.github` itself runs 8 distinct
schedules (`agent-mention-router`, `audit-central-ruleset`, `hourly-review-repair`,
`organization-commercial-readiness-loop`, `pr-auto-rebase`, `pr-review-merge-scheduler`,
`repository-metadata-reconcile`, `sbom-inventory-scheduler`) — already the central scheduler this
task's Step 3 asked to consolidate *toward*. Per-repo counts, full list in the aggregate output;
most repos run 1-2 product-loop schedules of their own (`hourly-product-development.yml`,
`commercial-readiness*.yml`, etc.) that are product-specific automation, not CI/security gates, and
are out of scope for the CI-centralization goal.

## Duplicate-check check

No case was found in this 24h window where the *same* check category (e.g. CodeQL, Semgrep, secret
scan) runs from both a per-repo workflow file and an independent org-required workflow on the same
head for the same purpose — `docs/doctoring/ci-workflow-duplication-audit-20260902.md` (existing,
2026-09-02) already covers this ground in more depth than this session re-derived and found the same:
duplication is not the primary driver of queue depth.

## What this baseline changes about the task's plan

Given the above, the Step 2/3 "centralize workflows to fix queue stalls" framing needs one
correction before more PRs get written against it: **workflow centralization is real hygiene
(fewer files to keep in sync, one required-check set) but is not a fix for the current queue
depth**, per the existing, still-live doctoring finding. The concurrency-group gap search in this
session (`grep` across `.github/workflows/*.yml` for a missing `concurrency:` block) found no
event-triggered required workflow lacking one — the 6 files without a `concurrency:` block are all
`workflow_call` reusable workflows (concurrency is correctly the caller's job) or
`issue_comment`/`schedule`-triggered (not supersession-prone). That specific low-risk fix this task
proposed as the smallest first step is already done.
