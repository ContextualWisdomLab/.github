# Doctoring record: coalesce fail-open horizon N and re-enable gate (2026-09-18)

- **Date:** 2026-09-18
- **Subject:** Ground `DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS` (N) in the
  post-`#2242` / capacity / schedule-queue measurements, state why N is
  **not** the observed schedule-delivery lag, and freeze the operator
  re-enable gate for `OPENCODE_REVIEW_COALESCE_ENABLED` before any future
  flip to `true`.
- **Decision record:** keep N = **600 seconds** (10 minutes). Do **not** flip
  the repository variable in this change; leave
  `OPENCODE_REVIEW_COALESCE_ENABLED=false` until the re-enable gate below is met.
- **Code path (already on `main` via `#2233`):**
  `scripts/ci/pr_review_merge_scheduler_core.py` —
  `recent_coalesce_tick_completed()` / `dispatch_opencode_review()` fail-open.
- **PR:** this commit's pull request.

## What fail-open guarantees

When `OPENCODE_REVIEW_COALESCE_ENABLED=true`, a synchronize/push-triggered
scheduler pass that sees a head still inside the 300s push-burst settling window
**defers** dispatch only if a coalesce tick completed with
`conclusion=success` within the last N seconds. Otherwise it **fail-opens** and
dispatches immediately. Reviews therefore never depend solely on the
`schedule:` cron in `.github/workflows/opencode-review-coalesce-tick.yml`.

Skipped / cancelled / failed ticks never count as liveness
(`recent_coalesce_tick_completed()` requires `conclusion == "success"`).

## Measured inputs (not invented)

| Source | What it measured | Figure used here |
|---|---|---|
| `docs/doctoring/actions-capacity-root-cause-20260917.md` | Push-burst gap density across 4 repos (419 gaps): density halves at **300s** | Settling window (`DEFAULT_COALESCE_WINDOW_SECONDS = 300`); cron `*/5` matches that window |
| `docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md` | After `#2242`, first delivered tick `35249460935` skipped in **1s**; schedule delivery still lagged (~40m after merge; earlier same-day gap ~5.5h) | Proves disabled ticks skip before admission; proves **delivery lag ≠ tick wall time** |
| `docs/doctoring/schedule-queue-post-2242-admission-levers-20260917.md` (PR `#2247`) | Through `18:31Z`, no new tick after `16:54Z` (~**97 minutes** between deliveries) while other schedule workflows sat multi-hour `queued` | Confirms under saturation, cron is not a reliable 5-minute heartbeat |

## Why N = 600 (and why it is not 40m / 97m)

`DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS = 600` is **two healthy cron periods**
(2 × 5 minutes), not the measured schedule-delivery lag.

| Candidate for N | Verdict |
|---|---|
| Measured delivery lag (~40m / ~97m / multi-hour) | **Reject as the fail-open horizon.** That lag is an org admission / GitHub schedule-delivery symptom under the plan concurrent-job ceiling. Encoding it into N would keep deferring reviews for the entire lag whenever a tick had succeeded once, recreating "reviews wait on schedule." Fail-open exists so that under that lag the synchronize path takes over within minutes. |
| One cron period (300s) | Too tight: a single slightly late healthy tick would fail-open every push inside the settling window and erase coalescing on an otherwise healthy schedule. |
| Two cron periods (**600s**) | **Keep.** Allows one missed/late healthy tick without abandoning coalescing; forces fail-open as soon as the tick path is no longer acting like a live `*/5` heartbeat. Under the measured 40–97m+ delivery gaps, fail-open correctly dominates until capacity recovers and successful ticks resume. |

So: schedule lag measurements justify **having** fail-open and keeping the
flag off until live verification; they do **not** justify widening N to match
the lag.

## Re-enable gate for `OPENCODE_REVIEW_COALESCE_ENABLED`

Do **not** set the variable to `true` until **all** of the following hold.
These are operator criteria; this repository change does not flip the variable.

1. **≥3 live successful ticks** on workflow `opencode-review-coalesce-tick.yml`
   (id `360129488`) with `conclusion=success` (not `skipped`), each finishing
   without multi-hour inert queue wait attributable to a step-scoped gate
   regression. Prefer consecutive deliveries that demonstrate the `*/5`
   heartbeat is actually alive under then-current capacity.
2. **One real push-burst verification** on an open product PR: several
   synchronize pushes inside the 300s window must (a) defer while a fresh
   successful tick is within N, and (b) **fail-open to immediate dispatch**
   if the tick path goes stale (no `success` within 600s) — proving reviews
   never depend solely on schedule.
3. Job-level gate still on `main`:
   `if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'` ahead of `runs-on`
   (`tests/test_opencode_review_coalesce_tick.py`).
4. Fail-open helpers still present and pinned:
   `DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS == 600`,
   `recent_coalesce_tick_completed()` success-only,
   `dispatch_opencode_review()` fail-open branch (`#2233` + this record's
   contract tests).

Until then the live value must remain `false` (confirmed
`2026-09-17T04:21:48Z` at the start of this work; re-check before any flip).

### Suggested flip procedure

```text
1. Confirm OPENCODE_REVIEW_COALESCE_ENABLED is still false.
2. Observe ≥3 conclusion=success ticks on workflow 360129488.
3. Run one deliberate push-burst on a throwaway/product PR; confirm defer + fail-open.
4. gh variable set OPENCODE_REVIEW_COALESCE_ENABLED --body true -R ContextualWisdomLab/.github
5. Watch the next ticks; if fail-open is unhealthy or ticks queue for hours without success, set false again.
```

## Explicit non-changes

- Do not widen N to the 40m/97m schedule-delivery measurements.
- Do not move the tick gate back to step scope (`#2242`).
- Do not set `cancel-in-progress: true` on the tick concurrency group.
- Do not add model-path timeouts or weaken required-check names.

## Audit trail

- `#2233` merge `d35788d73` — fail-open implementation.
- `#2242` / `#2244` — job-level skip + post-merge live verify.
- Measurements cited above; schedule-queue lever verdict in `#2247` doctoring.
- Repo variable
  `repos/ContextualWisdomLab/.github/actions/variables/OPENCODE_REVIEW_COALESCE_ENABLED`.
