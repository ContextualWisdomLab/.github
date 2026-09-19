# Doctoring record: coalesce fail-open horizon N (measurement-unset default) (2026-09-18)

- **Date:** 2026-09-18
- **Subject:** Calibrate (or refuse to invent) `DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS`
  from live Actions evidence; keep `OPENCODE_REVIEW_COALESCE_ENABLED=false`.
- **Decision record:** [ADR-0028](../adr/0028-opencode-review-coalesce-fail-open.md) —
  `DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS = 0` (unset). The zero-success sample
  authorizes no positive horizon or re-enable rule.
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
| Invented 600 = 2 × cron without success-tick evidence | **Reject.** Neither a default nor an operator override is authorized by this sample. |
| **0 (unset)** | **Keep as default.** Measurement-insufficient path: fail-open always when coalesce is enabled. |

## Re-enable authority for `OPENCODE_REVIEW_COALESCE_ENABLED`

This sample contains zero successful ticks, so **no positive N or re-enable decision is authorized**.
Keep the live value `false` (confirmed
`updated_at=2026-09-17T04:21:48Z` at measurement time).

A separately reviewed follow-up must, before collecting decision evidence:

1. State the sampling design, liveness estimand, error target, failure
   denominator, and treatment of queue saturation and missing ticks.
2. Derive the horizon and decision rule from that design rather than a fixed
   observation count, cron multiple, or fallback.
3. Bind the observed successful-tick runs and calculated result to exact,
   immutable workflow-run evidence.
4. Validate both defer-while-fresh and fail-open-when-stale on a real
   push-burst while preserving the job-level gate on `main`.

Until that follow-up passes exact-head review and checks, leave
`OPENCODE_REVIEW_COALESCE_TICK_MAX_AGE_SECONDS` unset and
`OPENCODE_REVIEW_COALESCE_ENABLED=false`.

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
