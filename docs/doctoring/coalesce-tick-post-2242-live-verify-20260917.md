# Doctoring record: post-#2242 coalesce tick live verify + re-enable criteria (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** After `#2242` restored the job-level
  `OPENCODE_REVIEW_COALESCE_ENABLED` gate, confirm the next schedule ticks
  finish as `completed`/`skipped` (or later `success` when enabled) within
  seconds — not multi-hour `queued` — and state when the flag may safely be
  flipped back to `true`.
- **Decision record:** none — live verification plus recommended re-enable
  criteria. Flipping the repo variable remains an explicit operator action.
- **PR:** this commit's pull request.

## Preconditions verified on `main`

| Check | Evidence |
|---|---|
| `#2242` merged | `3449d0020ffac86315ecccfb9d5a1dd3bf421834` at `2026-09-17T16:14:00Z` |
| Job-level gate restored | `origin/main:.github/workflows/opencode-review-coalesce-tick.yml` has `if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'` on `coalesce-tick`; no step-scoped inert `echo`/`exit 0` gate |
| Flag still off | repo variable `OPENCODE_REVIEW_COALESCE_ENABLED=false` (unchanged since `2026-09-17T04:21:48Z`) |
| Stuck inert waiter cleared | run `35219385415` reached `completed`/`cancelled` at `15:36:29Z` (concurrency group no longer holds a forever-pending inert tick) |
| Prior healthy skip baseline | run `35191169833` (job-level-gate era) `06:44:23Z` → `completed`/`skipped` by `06:44:24Z` (1s) |

Repair intent (from `#2242` / `docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`):
disabled ticks must skip **before runner admission** so they do not compete for
the plan concurrent-job ceiling.

## Live observation window (post-merge)

Sampled via
`repos/ContextualWisdomLab/.github/actions/workflows/opencode-review-coalesce-tick.yml/runs`
(workflow id `360129488`).

| Sample time (UTC) | `total_count` | Newest run | Status / conclusion | Notes |
|---|---|---|---|---|
| `16:36Z` (~22m after merge) | 2 | `35219385415` | completed / cancelled | No post-`#2242` schedule run yet |
| `16:43Z` | 2 | same | same | Still only the pre-merge pair |
| `16:48Z` (~34m after merge) | 2 | same | same | Still no `queued` and no `skipped` successor |
| `17:06Z` (~52m after merge) | 3 | **`35249460935`** | **completed / skipped** | First post-`#2242` delivery |

### Reading

1. **No multi-hour `queued` inert tick has reappeared after `#2242`.** That is the
   failure mode `#2242` fixed. Under the step-scoped gate, the first post-`#2232`
   schedule delivery created `35219385415` and left it `queued` for ~3.5h. After
   the job-level gate returned, the next delivered tick never entered `queued`.
2. **Schedule delivery still lags the `*/5` cron under saturation.** The first
   post-merge delivery arrived at `16:54:29Z` (~40m after merge), consistent with
   earlier same-day gaps (`06:44Z` → `12:07Z`, ~5.5h) documented in
   `docs/doctoring/actions-queue-24h-remeasurement-20260917.md`. Missed intervals
   are not backfilled as a stack of five-minute runs.
3. **Positive confirmation landed.** Run `35249460935` matches `#2242`'s
   acceptance check: flag still `false`, `conclusion=skipped`, wall time 1s,
   `head_sha=3449d0020ffa` (the `#2242` merge).

### First post-`#2242` tick

| Field | Value |
|---|---|
| Run id | `35249460935` (run_number 3) |
| Created / updated | `2026-09-17T16:54:29Z` → `2026-09-17T16:54:30Z` |
| Conclusion | `skipped` |
| Elapsed | **1s** |
| Head SHA | `3449d0020ffa` (`#2242` merge) |
| URL | https://github.com/ContextualWisdomLab/.github/actions/runs/35249460935 |

## Recommended `OPENCODE_REVIEW_COALESCE_ENABLED` re-enable criteria

Do **not** flip the variable to `true` until all of the following hold. These are
operator criteria, not code changes.

### Must-have (gate health)

1. **Post-`#2242` disabled-tick proof.** At least **one** (preferably **two**)
   schedule runs on workflow `360129488` with
   `conclusion=skipped`, wall time ≤ ~10s, and `head_sha` containing the
   job-level gate (`≥ 3449d0020`). **Met** by `35249460935` (1s skip on
   `3449d0020`); a second skipped delivery remains preferred before flip but
   is not blocking once capacity criteria (#4–#5) are accepted.
2. **Job-level gate still on `main`.**
   `if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'` remains on the
   `coalesce-tick` **job**, not moved back to a step. Contract:
   `tests/test_opencode_review_coalesce_tick.py`.
3. **Fail-open still present.** `recent_coalesce_tick_completed()` still requires
   `conclusion == "success"` and the scheduler still fail-opens when no fresh
   successful tick exists (`#2233`). Skipped/cancelled ticks must never count as
   coalesce liveness.

### Should-have (capacity / blast radius)

4. **Org admission headroom or accepted fail-open.** A live census of
   org-wide `in_progress` vs plan concurrent-job ceiling (~60; see
   `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`) and queued
   depth (`docs/doctoring/actions-queue-24h-remeasurement-20260917.md`).
   - Prefer enable when `in_progress` is clearly below ceiling and queued depth
     is not on the order of 10³, **or**
   - Explicitly accept that enabled ticks may still sit `queued` for hours and
     that `#2233` fail-open will temporarily bypass coalesce deferral until a
     `success` tick completes. Enabling under deep saturation without that
     acceptance recreates "reviews never dispatch" rather than "inert ticks
     clog the queue."
5. **Operator watch on the first enabled ticks.** After flipping the variable,
   watch the next 2–3 schedule deliveries until each reaches
   `conclusion=success` (or a documented fail-open dispatch path fires). Do not
   walk away after only seeing `queued`.
6. **No concurrent experiment that reintroduces step-scoped observability.**
   Run-record hunger must not override the admission-skip contract.

### Explicit non-criteria

- **Do not** treat schedule-delivery lag (hours between cron fires) as a reason
  to widen the tick job or move the gate to steps again.
- **Do not** set `cancel-in-progress: true` to "fix" admission delay — that
  cancels mid-org dispatch (`docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`).
- **Do not** enable solely because `#2242` merged; merge proves the code path,
  not live schedule behavior under today's queue.

### Suggested flip procedure

```text
1. Confirm ≥1 post-#2242 skipped tick (table above filled).
2. Re-sample org in_progress / queued; decide accept-fail-open vs wait-for-relief.
3. gh variable set OPENCODE_REVIEW_COALESCE_ENABLED --body true -R ContextualWisdomLab/.github
4. Watch next ticks for conclusion=success; confirm recent_coalesce_tick_completed path.
5. If ticks queue for hours, leave flag on only if fail-open is observed healthy; else set false again.
```

## Verdict (as of `17:06Z`)

| Claim | Status |
|---|---|
| `#2242` on `main` with job-level skip-before-admission | **Confirmed** |
| No post-merge multi-hour inert `queued` tick | **Confirmed** |
| Next tick completes `skipped` in seconds | **Confirmed** — `35249460935` in 1s |
| Must-have #1 (post-`#2242` disabled-tick proof) | **Met** |
| Safe to set `OPENCODE_REVIEW_COALESCE_ENABLED=true` now | **Not yet** — still need should-have capacity/fail-open acceptance (#4–#5); prefer a second skipped tick if schedule delivers one before flipping |

## Audit trail

- `ContextualWisdomLab/.github#2242` merge `3449d0020` @ `2026-09-17T16:14:00Z`
- `repos/ContextualWisdomLab/.github/actions/workflows/360129488/runs`
- `repos/ContextualWisdomLab/.github/actions/runs/35249460935` (post-`#2242` skipped)
- `repos/ContextualWisdomLab/.github/actions/runs/35219385415`
- `repos/ContextualWisdomLab/.github/actions/runs/35191169833`
- `repos/ContextualWisdomLab/.github/actions/variables/OPENCODE_REVIEW_COALESCE_ENABLED`
- Prior:
  `docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`,
  `docs/doctoring/actions-queue-24h-remeasurement-20260917.md`,
  `docs/doctoring/actions-schedule-run-records-20260917.md`,
  `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`
