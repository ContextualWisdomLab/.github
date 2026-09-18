# ADR-0028: OpenCode review coalesce fail-open when tick liveness is unmeasured

- **Status:** Accepted
- **Date:** 2026-09-18
- **Scope:** `scripts/ci/pr_review_merge_scheduler_core.py`
  (`dispatch_opencode_review`, `recent_coalesce_tick_completed`,
  `DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS`),
  `.github/workflows/opencode-review-coalesce-tick.yml`, repository variable
  `OPENCODE_REVIEW_COALESCE_ENABLED`
- **Does not amend:** ADR-0005 / product-goal §8 (no model-path wall-clock
  timeouts); ADR-0022 (workflow-runs cache); required-check context names

## Problem

Push-burst coalescing (`#2231`) defers synchronize-triggered OpenCode review
dispatch while a head is still inside a 300s settling window, relying on a
`*/5` coalesce tick to dispatch once the head stabilizes. If that schedule
stalls — as measured when the tick workflow produced no usable runs under
Actions saturation and the flag was set `false` at `2026-09-17T04:21:48Z` —
reviews that only wait for the tick never dispatch. Fail-open (`#2233`) already
dispatches immediately when no tick completed with `conclusion=success` within
horizon N. N itself must come from measurement of successful-tick cadence, not
from inventing a constant or from encoding multi-hour schedule-delivery lag
(which would recreate "reviews wait on cron").

## Constraints

1. Do **not** set `OPENCODE_REVIEW_COALESCE_ENABLED=true` in this decision.
2. Required OpenCode / Strix / Noema / Semgrep context names stay stable.
3. Skipped, cancelled, and failed ticks never count as coalesce liveness.
4. Do not widen N to measured schedule-delivery lag (~40m / ~97m / multi-hour).
5. Do not add model-path timeouts.

## Measurement (2026-09-18)

Sampled with the worker token against workflow id `360129488`
(`.github/workflows/opencode-review-coalesce-tick.yml`):

| Observation | Value |
|---|---|
| `total_count` | 6 |
| `conclusion=success` | **0** |
| `conclusion=skipped` | 5 (flag still false; job-level gate) |
| `conclusion=cancelled` | 1 (pre-`#2242` inert waiter `35219385415`) |
| Gaps between schedule `created_at` (all conclusions) | min 129.2m, median 181.6m, max 323.4m (n=5) |

There is **no successful-tick inter-arrival sample** from which to calibrate N.
Sibling schedule health (hourly-review-repair success gaps median ~50m) is
capacity context only; it is not coalesce-tick liveness.

Prior doctoring (`coalesce-tick-post-2242-live-verify-20260917.md`,
`actions-capacity-root-cause-20260917.md`) still grounds the 300s settling
window and shows why schedule delivery lag must not become N.

## Decision

1. **Keep fail-open on the synchronize path** (`#2233`): when coalescing is
   enabled and the head is inside the settling window, defer only if
   `recent_coalesce_tick_completed()` sees a `conclusion=success` tick within
   N; otherwise dispatch immediately.
2. **Leave N unset by default** (`DEFAULT_COALESCE_TICK_MAX_AGE_SECONDS = 0`).
   Non-positive N means "tick path is not proven live" → always fail-open to
   immediate dispatch when coalesce is enabled. This is the measurement-
   insufficient path required by this ADR.
3. **Candidate N after live success ticks exist:** 600 seconds (two healthy
   `*/5` cron periods). Operators may set
   `OPENCODE_REVIEW_COALESCE_TICK_MAX_AGE_SECONDS=600` (or a value derived from
   measured success-tick gaps) only after the re-enable gate below; do not
   bake lag into the default.
4. **Re-enable gate for the coalesce flag** (operator only; this ADR does not
   flip the variable): ≥3 live `conclusion=success` ticks on workflow
   `360129488` **and** one real push-burst verifying defer-while-fresh plus
   fail-open-when-stale. Until then
   `OPENCODE_REVIEW_COALESCE_ENABLED` remains `false`.

## Consequences

- Enabling the flag before successful ticks exist is latency-safe: every fresh
  head fail-opens to immediate dispatch (coalesce deferral is inert until N>0
  and ticks succeed).
- Once ≥3 success ticks are observed, a follow-up can set a positive N from
  that cadence (starting candidate 600s) without changing required contexts.
- PR `#2249`'s prose that baked N=600 as the default is superseded by this
  measurement-insufficient default; its re-enable gate and "do not encode lag
  as N" rationale remain binding.

## Audit trail

- `#2231` coalesce tick (inert by default); `#2233` fail-open implementation.
- `#2242` / `#2244` job-level skip + live verify; flag `false` since
  `2026-09-17T04:21:48Z`.
- Doctoring: `docs/doctoring/coalesce-fail-open-tick-max-age-20260918.md`.
