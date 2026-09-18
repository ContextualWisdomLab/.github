# Doctoring record: coalesce fail-open horizon N (measurement-unset default) (2026-09-18)

- **Date:** 2026-09-18
- **Subject:** Calibrate (or refuse to invent) `DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS`
  from live Actions evidence; keep `OPENCODE_REVIEW_COALESCE_ENABLED=false`.
- **Decision record:** [ADR-0028](../adr/0028-opencode-review-coalesce-fail-open.md) —
  `DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS = 0` (unset) until successful-tick
  cadence exists; candidate positive N = **600s** (two healthy `*/5` periods)
  via env override only after the re-enable gate.
- **Code path:** `scripts/ci/pr_review_merge_scheduler_core.py` —
  `recent_coalesce_tick_completed()` / `dispatch_opencode_review()` fail-open
  (`#2233`), default horizon updated by this record's PR.
- **Supersedes default in:** open `#2249` prose that baked N=600 as the code
  default without a success-tick sample (re-enable gate text still applies).

## What fail-open guarantees

When `OPENCODE_REVIEW_COALESCE_ENABLED=true`, a synchronize/push-triggered
scheduler pass that sees a head still inside the 300s push-burst settling window
**defers** dispatch only if a coalesce tick completed with
`conclusion=success` within the last N seconds **and** N is positive. Otherwise
it **fail-opens** and dispatches immediately. Reviews therefore never depend
solely on the `schedule:` cron in `.github/workflows/opencode-review-coalesce-tick.yml`.

Skipped / cancelled / failed ticks never count as liveness.

## Live measurement (this session)

Queried
`GET /repos/ContextualWisdomLab/.github/actions/workflows/360129488/runs?per_page=100`
with the worker `GH_TOKEN` at ~`2026-09-18T04:00Z` (UTC):

| Field | Value |
|---|---|
| `total_count` | 6 |
| `conclusion=success` | **0** |
| `conclusion=skipped` | 5 |
| `conclusion=cancelled` | 1 (`35219385415`) |
| Newest run | `35292469590` @ `2026-09-18T00:44:49Z` → skipped in 1s |
| Schedule `created_at` gaps (n=5) | min **129.2m**, median **181.6m**, max **323.4m** |

**Successful-tick gap sample size = 0** → N cannot be proposed from measured
success cadence. Per ADR-0028, leave the default unset (0) so coalesce-enabled
dispatch always fail-opens until operators supply a positive
`OPENCODE_REVIEW_COALESCE_TICK_MAX_AGE_SECONDS` after live success ticks exist.

### Context measurements (not used as N)

| Source | Figure | Use |
|---|---|---|
| `docs/doctoring/actions-capacity-root-cause-20260917.md` | Push-burst density halves at **300s** | Settling window / cron `*/5` only |
| `docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md` | First post-`#2242` tick skipped in 1s; ~40m delivery lag | Gate health; proves lag ≠ tick wall time |
| Schedule-queue doctoring / `#2247` | ~97m between deliveries under saturation | Justifies **having** fail-open; **rejects** encoding lag as N |
| hourly-review-repair schedule successes (same day sample) | success gaps median ~50m | Org schedule capacity context only |

## Why default N = 0 (and why not 40m / 97m / invented 600)

| Candidate | Verdict |
|---|---|
| Measured delivery lag (~40m / ~97m / multi-hour) | **Reject as N.** Would keep deferring reviews for the entire lag after one success, recreating schedule dependence. |
| Invented 600 = 2 × cron without success-tick evidence | **Reject as code default.** Valid only as a **candidate override** once ≥3 `conclusion=success` ticks prove the `*/5` heartbeat is alive. |
| **0 (unset)** | **Keep as default.** Measurement-insufficient path: fail-open always when coalesce is enabled. |

## Re-enable gate for `OPENCODE_REVIEW_COALESCE_ENABLED`

Do **not** set the variable to `true` until **all** of the following hold:

1. **≥3 live successful ticks** on workflow `360129488` with
   `conclusion=success` (not `skipped`), without multi-hour inert queue wait
   from a step-scoped gate regression.
2. **One real push-burst verification** on an open product PR: several
   synchronize pushes inside the 300s window must (a) defer while a fresh
   successful tick is within a **positive** N, and (b) **fail-open** if the
   tick path goes stale.
3. Job-level gate still on `main`:
   `if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'` ahead of `runs-on`.
4. After (1), set a positive N (candidate **600**) via
   `OPENCODE_REVIEW_COALESCE_TICK_MAX_AGE_SECONDS` or a follow-up PR that
   cites the measured success-tick gaps — then flip the flag.

Until then the live value must remain `false` (confirmed
`updated_at=2026-09-17T04:21:48Z` at measurement time).

### Suggested flip procedure

```text
1. Confirm OPENCODE_REVIEW_COALESCE_ENABLED is still false.
2. Observe ≥3 conclusion=success ticks on workflow 360129488; record gaps.
3. Set OPENCODE_REVIEW_COALESCE_TICK_MAX_AGE_SECONDS to the measured/candidate N (start 600).
4. Run one deliberate push-burst; confirm defer + fail-open.
5. gh variable set OPENCODE_REVIEW_COALESCE_ENABLED --body true -R ContextualWisdomLab/.github
6. If ticks queue for hours without success, set the flag false again.
```

## Explicit non-changes

- Do not flip `OPENCODE_REVIEW_COALESCE_ENABLED` in this change.
- Do not widen N to schedule-delivery lag.
- Do not move the tick gate back to step scope (`#2242`).
- Do not rename required check contexts.
- Do not add model-path timeouts.

## Audit trail

- `#2233` fail-open implementation on `main`.
- `#2242` / `#2244` job-level skip + post-merge live verify.
- ADR-0028; this measurement session on `coalesce-fail-open-v4`.
- Repo variable
  `repos/ContextualWisdomLab/.github/actions/variables/OPENCODE_REVIEW_COALESCE_ENABLED`.
