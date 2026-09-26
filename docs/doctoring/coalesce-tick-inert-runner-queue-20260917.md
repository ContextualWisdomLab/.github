# Doctoring record: coalesce tick run 35219385415 queued 3h+ for an inert job (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** Why `OpenCode Review Coalesce Tick` run `35219385415` stayed
  `status=queued` for more than two hours on `ContextualWisdomLab/.github`,
  whether a lighter job or concurrency change is warranted, and the repair.
- **Decision record:** none — diagnostic plus a workflow gate correction.
- **PR:** this commit's pull request.

## Live evidence (gathered 2026-09-17)

| Observation | Evidence |
|---|---|
| Stuck run | `35219385415`, event `schedule`, created `2026-09-17T12:07:50Z`, still `status=queued` / `conclusion=null` at `15:32Z` (~3h25m) before operator cancel |
| Head at enqueue | `130ce425f74c` (post-`#2235`; coalesce tick workflow already on `main` via `#2232`) |
| Workflow inventory | Only **2** runs total for workflow id `360129488`: pre-gate `35191169833` and the stuck `35219385415` |
| Pre-`#2232` contrast | `35191169833` at `06:44:23Z` → `completed`/`skipped` by `06:44:24Z` (1s; job-level gate era) |
| Coalesce flag | repo variable `OPENCODE_REVIEW_COALESCE_ENABLED=false` (updated `2026-09-17T04:21:48Z`) |
| Runner label | workflow `runs-on: ubuntu-24.04` (not floating `ubuntu-latest`) |
| Concurrency | group `opencode-review-coalesce-tick`, `cancel-in-progress: false` |
| Org ceiling context | Prior same-day census: ~48 org-wide `in_progress` vs ~1,911 `queued` (`docs/doctoring/actions-queue-24h-remeasurement-20260917.md`); plan concurrent-job ceiling ~60 (`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`) |

Operator cancel of `35219385415` at `15:36:29Z` reached `completed`/`cancelled` so the concurrency group no longer holds a forever-pending inert tick.

## Root cause

Not a missing runner label, not a hung step, and not a defect in the
org-wide GraphQL / scheduler loop (those steps never started).

`#2232` moved `OPENCODE_REVIEW_COALESCE_ENABLED` from a **job-level** `if:` to
a **step-level** gate so that every five-minute cron would still produce a
visible run record while coalescing stayed off. That succeeded at producing
records, but it also forced GitHub to **admit the job into the shared runner
queue** even when the only work would be an inert `echo` and `exit 0`.

Under the org's plan concurrent-job ceiling the inert job sits behind ~10³
other queued runs. `cancel-in-progress: false` is correct for an in-flight
org-wide dispatch (do not cut mid-repository), and with at most one active +
one pending member it also explains why the five-minute cron did not
accumulate unbounded stacked run records while `35219385415` remained the
active waiter.

The earlier claim that a job-level `if:` "suppressed every run record"
(`docs/doctoring/actions-schedule-run-records-20260917.md`) does not hold
against `35191169833`, which is a completed/`skipped` schedule run from the
job-level-gate era. Skipped jobs still create run records; they simply do not
wait for a runner.

## What is / is not warranted

| Lever | Verdict |
|---|---|
| Lighter job when flag is false | **Yes** — restore job-level `if:` so disabled ticks skip before runner admission |
| Change `cancel-in-progress` to `true` | **No** — would cancel an in-flight org-wide dispatch mid-repository; does not shorten admission wait for the active waiter |
| Different `runs-on` label | **No** — already pinned to `ubuntu-24.04`; hosted labels share the same plan ceiling |
| Plan-tier / more concurrent jobs | Owner-only; still the only way to make an *enabled* tick admit quickly under saturation |
| Scheduler fail-open (`#2233`) | Keep — when the flag is on and a real tick queues for hours, dispatch must not defer forever |

When coalescing is later enabled, a real tick still competes for the same
ceiling; that is accepted. `recent_coalesce_tick_completed()` must treat only
`conclusion=success` as a healthy tick so a disabled-era `skipped` run cannot
be mistaken for proof that coalesce dispatch is alive after the flag flips on.

## Repair

1. Restore job-level `if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'` on
   `coalesce-tick` and drop the step-scoped inert/echo gate.
2. Require `conclusion == "success"` in `recent_coalesce_tick_completed()`.
3. Cancel the stuck inert run (`35219385415`) so it no longer occupies the
   concurrency group (done live during this investigation).

## Audit trail

- `repos/ContextualWisdomLab/.github/actions/runs/35219385415`
- `repos/ContextualWisdomLab/.github/actions/runs/35191169833`
- `repos/ContextualWisdomLab/.github/actions/workflows/360129488/runs`
- `repos/ContextualWisdomLab/.github/actions/variables/OPENCODE_REVIEW_COALESCE_ENABLED`
- Prior related records:
  `docs/doctoring/actions-schedule-run-records-20260917.md`,
  `docs/doctoring/actions-queue-24h-remeasurement-20260917.md`,
  `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`,
  `docs/doctoring/actions-capacity-root-cause-20260917.md`
