# Doctoring record: scheduled workflows still enqueue run records under saturation; coalesce tick had none (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** After org-wide Actions saturation (~01:32Z), operators observed queued
  schedule runs sitting for 3+ hours and believed no new schedule records were being
  created. The coalesce tick workflow (`opencode-review-coalesce-tick.yml`, id
  `360129488`) showed zero runs while `OPENCODE_REVIEW_COALESCE_ENABLED=false`.
- **Decision record:** none — diagnostic plus a step-scoped gate repair for the tick
  workflow.

## Measured evidence

REST sample gathered 2026-09-17 (`repos/ContextualWisdomLab/.github/actions/runs`):

| Observation | Evidence |
|---|---|
| Schedule runs still created after 01:32Z | `35170930384` Repository Metadata Reconcile at `2026-09-17T01:32:08Z` (queued); `35182924821` Daily Review Recovery at `04:42:31Z` (queued); `35183563151` PR Auto Rebase at `04:52:33Z` (queued) |
| Six schedule runs currently queued | `status=queued&event=schedule` → `total_count=6` |
| Coalesce tick zero runs | `actions/workflows/opencode-review-coalesce-tick.yml/runs` → `total_count=0` |
| Coalesce flag off | repo variable `OPENCODE_REVIEW_COALESCE_ENABLED=false` |

The org-wide stall is therefore **runner admission under the plan concurrent-job ceiling**
(`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`), not GitHub ceasing to
create schedule run records entirely. New schedule records continue to arrive; they
queue behind thousands of other jobs and rarely reach `in_progress`.

## Coalesce tick zero-run root cause

The tick workflow used a **job-level** `if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'`.
When the variable is `false`, GitHub does not enqueue a workflow run for that schedule
event at all — confirmed live: zero runs since merge at `f9863d941` even though the
five-minute cron has elapsed many times. That made the tick invisible in the Actions UI
and prevented `recent_coalesce_tick_completed()` from ever observing a completed tick,
which would have blocked review dispatch indefinitely had coalescing stayed enabled without
the scheduler fail-open repair.

## Repair

1. **Scheduler fail-open** (`scripts/ci/pr_review_merge_scheduler_core.py`): when
   coalescing is enabled but no tick completed within `600s` (2× the cron interval),
   `dispatch_opencode_review()` dispatches immediately instead of returning `coalescing`.
2. **Tick observability** (`opencode-review-coalesce-tick.yml`): move the flag gate from
   job scope to step scope so every cron produces a run record; only the substantive steps
   are skipped when the variable is false.

## Audit trail

- `/tmp/gh-cache-lead/schedule-runs-all.json`, `/tmp/gh-cache-lead/schedule-queued.json`
  (REST, 2026-09-17).
- `repos/ContextualWisdomLab/.github/actions/workflows/opencode-review-coalesce-tick.yml/runs`.
- `docs/doctoring/actions-capacity-root-cause-20260917.md`,
  `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`.
