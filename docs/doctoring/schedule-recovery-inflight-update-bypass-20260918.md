# Doctoring record: schedule recovery bypasses #1935 in-flight hold (2026-09-18)

- **Date:** 2026-09-18
- **Subject:** Daily merge-scheduler recovery (`GITHUB_EVENT_NAME=schedule`) was
  inert under Actions queue saturation: OpenCode-needing heads were behind, so
  review could not dispatch, and `#1935`'s in-flight check hold blocked
  `update_branch`, so recovery neither updated nor dispatched — yet exited
  success. Same class as `fmls#2006`.
- **Holds:** ContextualWisdomLab/.github#2267 (fail-loud taxonomy + effective
  limits) until this dispatch path is proven; do not merge on taxonomy alone.

## Measured evidence (cron run 35202348887, 2026-09-17)

| Observation | Evidence |
|---|---|
| Reviews were triggered | Log: `TRIGGER_REVIEWS: true` |
| Budgets were non-zero | `REVIEW_DISPATCH_LIMIT_INPUT: 4`, `REVIEW_ADMISSION_DISPATCH_BUDGET: 1` |
| Local schedule scan ran | 100 decisions; not a targeted-dispatch reject |
| OpenCode-needing heads blocked on freshness | PR #834 `update_branch` (no in-flight); PRs #1198, #1215, #1238, #1519 `wait` with "outdated before review dispatch, but current-head checks are still queued or running" |
| Counts | `update_branch=1`, `wait=21`, **no `review_dispatch` key** (`dispatched=0`) |
| Contrast when head is current | Prior cron 35076102529: `PR #1519: review_dispatch: ... OpenCode dispatched` |

Root cause is a **definition / pre-dispatch filter mismatch**, not a zero budget
or a false `TRIGGER_REVIEWS`. The five OpenCode-needing heads were all outdated
before review dispatch; four were soft-held by `#1935`.

## Repair (smaller policy change)

On `GITHUB_EVENT_NAME=schedule` only, when an OpenCode-needing head is behind
and the only blocker is `#1935`'s in-flight check hold:

1. **Prefer `update_branch`** despite queued/running current-head checks, with a
   loud `::warning` citing the `#1935` tradeoff (discard in-flight evidence so
   daily recovery is not inert).
2. If the branch-update budget is already exhausted on that schedule tick,
   **fall through to `review_dispatch` / `security_dispatch`** on the behind
   head with an explicit warning, rather than soft-idle.

Event-driven paths (`pull_request_target`, `workflow_run`, …) keep the `#1935`
hold unchanged.

Companion observability (same PR #2267): `scheduler_effective_limits` prints
the live review-dispatch / branch-update / admission values every run;
`classify_review_recovery` / `emit_review_recovery_signal` fail loud when
schedule recovery finds outdated OpenCode-needing heads and still produces
neither update nor dispatch.

## Audit trail

- Cron logs for `35202348887` and `35076102529` (Daily Review Recovery).
- `#1935` hold rationale in `CHANGELOG.md` / `inspect_pr` comment.
- Implementation: `scripts/ci/pr_review_merge_scheduler_core.py` schedule
  branch of the outdated-before-review path; tests in
  `tests/test_pr_review_merge_scheduler.py`.
