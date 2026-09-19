# Doctoring record: merge-scheduler `REVIEW_DISPATCH_LIMIT` throughput shaping (2026-09-18)

- **Date:** 2026-09-18
- **Subject:** Cap per-run OpenCode/Strix review dispatch budget so the merge
  scheduler shapes throughput under the org Actions plan ceiling, without
  disabling review dispatch.
- **Decision record:** operational var change plus fail-closed validation. The
  measured repo variable remains the authority; unset or blank has no invented fallback.
- **PR:** this commit's pull request.

## What changed (operational + durable)

| Lever | Before | After |
|---|---|---|
| Repo var `REVIEW_DISPATCH_LIMIT` | **4** | **1** (lead set at `2026-09-18T06:19:47Z` for immediate effect) |
| `workflow_call` input `review_dispatch_limit` default | `"1"` | none; caller or repo variable must provide authority |
| Shell empty fallback in `pr-review-merge-scheduler.yml` | `-1` (unlimited) | fail closed with an explicit configuration error |
| Explicit input/var value `-1` | unlimited | still unlimited when set deliberately |

Sibling budgets already aligned at 1 (or low single digits): `REVIEW_ADMISSION_DISPATCH_BUDGET`
defaults to 1 when unset; `BRANCH_UPDATE_LIMIT=1`; `ORG_SWEEP_REVIEW_DISPATCH_LIMIT=2`;
fix-scheduler `MAX_DISPATCHES` defaults to 1. Those sibling values are separate
operational authorities and are not reused as a fallback for this scheduler.

## Why 4 → 1 (not disable)

Each ruleset-injected merge-scheduler run can fan out up to `REVIEW_DISPATCH_LIMIT`
AI review dispatches (OpenCode / Strix / related). At **4**, concurrent scheduler
runs across repositories multiply that fan-out against an org concurrent-job
ceiling of roughly **60** (`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`).

Live queue snapshot before the var change (path
`~/.local/orca-watchdog/queue-before-061947.json`, measured
`2026-09-18T10:20:32Z` UTC — note the filename marks the earlier operational
cutover `061947Z`):

| Signal | Value |
|---|---|
| Org `queued` (sample) | ≈390 |
| Org `in_progress` | ≈17 |
| `.github` eligible non-draft unapproved proxy | ≈31 |
| Queued OpenCode Dispatch | ≈118 |
| Then-current `REVIEW_DISPATCH_LIMIT` | 4 |

This is **throughput shaping**, not a kill switch: reviews still dispatch, one
eligible current-head review per scheduler run by default. Work continues; only
the configured per-run burst width shrinks. `cancel-in-progress` concurrency
is already correct and was not touched. No age-based cancel. If the configured
variable is absent, dispatch stops with a configuration error rather than
silently choosing a rule-of-thumb budget.

## Reversibility

Raise the repo variable (or pass an explicit `workflow_call` /
`repository_dispatch` `review_dispatch_limit`) to restore wider fan-out. Setting
the var or input to **`-1`** remains the documented unlimited path. Leaving the
var unset or blank now fails closed; it does not infer **1**, unlimited, or any
other decision-affecting budget.

## Out of scope

Trigger-narrowing and `ready_for_review` / synchronize deferral for AI-review
workflows are a separate thread and must not be reopened here.
