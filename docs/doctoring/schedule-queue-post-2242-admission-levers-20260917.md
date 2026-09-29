# Doctoring record: post-#2242 schedule queue — admission levers for coalesce tick (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** After `#2242` / `#2243` / `#2244`, live-verify whether schedule-triggered
  runs still sit `queued` for hours, whether coalesce tick workflow `360129488`
  still completes `skipped` in seconds when cron delivers, and whether the tick
  needs dedicated runner labels or a concurrency change beyond what already
  landed.
- **Decision record:** none — diagnostic. **No workflow code change** in this
  record: the investigated levers do not open a new admission path under the
  plan concurrent-job ceiling.
- **PR:** this commit's pull request.

## Preconditions on `main` at sample

| Check | Evidence |
|---|---|
| `#2242` job-level gate on `main` | `opencode-review-coalesce-tick.yml` still has `if: vars.OPENCODE_REVIEW_COALESCE_ENABLED == 'true'` on the `coalesce-tick` job (ahead of `runs-on`) |
| Flag still off | `OPENCODE_REVIEW_COALESCE_ENABLED=false` (updated `2026-09-17T04:21:48Z`) |
| Prior post-`#2242` skip proof | run `35249460935` `completed`/`skipped` in 1s at `16:54:29Z` (`docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md`) |
| Sample time (UTC) | `2026-09-17T18:31:38Z` |

## Live answers

### 1. Are schedule-triggered runs still sitting queued for hours?

**Yes.** Non-tick schedule workflows on `.github` still wait multi-hour for runner
admission (same plan-ceiling signature as
`docs/doctoring/actions-capacity-root-cause-20260917.md` and
`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`):

| Workflow | Run | Created (UTC) | Status at ~18:31Z | Notes |
|---|---|---|---|---|
| PR Auto Rebase | `35249946503` | `16:59:27Z` | `queued` (~1.5h so far) | Prior success `35216986242` wall `11:41Z`→`16:37Z` (~5h) |
| SBOM Inventory Scheduler | `35225408296` | `13:10:17Z` | `queued` (~5h+) | Newer hourly `35256139480` is `pending` behind it (`cancel-in-progress: false`) |
| Repository Metadata Reconcile | `35258328418` | `18:21:30Z` | `queued` (fresh) | Prior schedule `35228133081` wall `13:36Z`→`17:34Z` (~4h) |

Schedule **records continue to be created**; they queue behind the org concurrent-job
ceiling. This is not a regression of `#2242` and not evidence that GitHub stopped
enqueueing cron runs.

### 2. Is coalesce tick `360129488` getting skipped in seconds on recent cron?

**When a schedule delivery arrives: yes. On every `*/5` wall-clock tick: no.**

| Observation | Evidence |
|---|---|
| Latest tick | `35249460935` at `16:54:29Z` → `16:54:30Z`, `conclusion=skipped`, head `3449d0020ffa` (`#2242`) |
| Inventory since then | `total_count=3` — **no** new run between `16:54Z` and `18:31Z` (~97 minutes) |
| Failure mode that `#2242` fixed | Has **not** returned: no post-`#2242` multi-hour `queued` inert tick |

Reading: the job-level gate still skips **before runner admission** (1s
`completed`/`skipped`). Under saturation, GitHub's schedule delivery for this
workflow still lags the `*/5` cron — missed intervals are not backfilled as a
stack of five-minute runs (same pattern as
`docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md`). Delivery lag
must not be "fixed" by moving the flag back to step scope.

### 3. Dedicated runner labels or extra workflow concurrency?

| Lever | Verdict | Why |
|---|---|---|
| Dedicated / alternate hosted `runs-on` label | **No** | Tick already pins `ubuntu-24.04`. Hosted labels share the org plan concurrent-job ceiling (`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`; same conclusion in `docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`). Relabeling does not create a separate admission pool. |
| Self-hosted / separate capacity pool | Owner-only | Only owner plan/runner-pool change lifts the ceiling; not a workflow YAML fix in this repository alone. |
| New or tighter workflow `concurrency` | **No** | Group `opencode-review-coalesce-tick` with `cancel-in-progress: false` already present. Flipping cancel to `true` was rejected in `#2242`'s doctoring: it would cut an in-flight org-wide coalesce dispatch mid-repository and does not shorten admission wait for the active waiter. |
| Re-introduce step-scoped observability gate | **No** | That is the `#2232` regression `#2242` closed (inert job `35219385415` queued 3h+). |

## What is left (not this PR)

1. **Plan concurrent-job headroom** (or accepted multi-hour queue) before flipping
   `OPENCODE_REVIEW_COALESCE_ENABLED=true` — criteria unchanged from
   `docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md` §§4–5.
2. **Scheduler fail-open** (`#2233`) remains the safety net when an *enabled*
   tick sits `queued` for hours; do not disable it.
3. Optional follow-ups for *other* hourly schedules (e.g. SBOM
   `cancel-in-progress` so a stale queued hourly does not block a fresher one)
   are separate from coalesce-tick admission and are **not** claimed solved here.

## Verdict

| Claim | Status |
|---|---|
| Schedule runs still multi-hour `queued` under saturation | **Confirmed** (rebase / SBOM / metadata samples above) |
| Post-`#2242` coalesce tick skips in seconds when delivered | **Confirmed** (`35249460935`) |
| No post-`#2242` inert multi-hour queued tick | **Confirmed** through `18:31Z` |
| Tick needs dedicated labels or new concurrency | **Rejected** |
| Concrete coalesce-tick workflow code gap beyond `#2242`/`#2243`/`#2242` docs | **None** — doctoring only |

## Evidence commands

```bash
date -u +%Y-%m-%dT%H:%M:%SZ
gh api 'repos/ContextualWisdomLab/.github/actions/workflows/opencode-review-coalesce-tick.yml/runs?per_page=5' \
  --jq '{total: .total_count, runs: [.workflow_runs[]|{id,conclusion,status,created_at,updated_at,head_sha: .head_sha[0:12]}]}'
gh api 'repos/ContextualWisdomLab/.github/actions/workflows/pr-auto-rebase.yml/runs?per_page=3' \
  --jq '{runs: [.workflow_runs[]|{id,event,status,conclusion,created_at,updated_at}]}'
gh api 'repos/ContextualWisdomLab/.github/actions/workflows/sbom-inventory-scheduler.yml/runs?per_page=3' \
  --jq '{runs: [.workflow_runs[]|{id,event,status,conclusion,created_at,updated_at}]}'
gh api 'repos/ContextualWisdomLab/.github/actions/workflows/repository-metadata-reconcile.yml/runs?event=schedule&per_page=3' \
  --jq '{runs: [.workflow_runs[]|{id,status,conclusion,created_at,updated_at}]}'
gh api 'repos/ContextualWisdomLab/.github/actions/variables/OPENCODE_REVIEW_COALESCE_ENABLED' \
  --jq '{value, updated_at}'
python3 -m pytest tests/test_opencode_review_coalesce_tick.py -q
```

## Audit trail

- Sample window `2026-09-17T18:31:38Z` (UTC), REST via `gh api`.
- Workflow id `360129488` / `opencode-review-coalesce-tick.yml`.
- Prior:
  `docs/doctoring/actions-capacity-root-cause-20260917.md`,
  `docs/doctoring/actions-schedule-run-records-20260917.md`,
  `docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`,
  `docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md`,
  `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`,
  `docs/doctoring/actions-queue-24h-remeasurement-20260917.md`.
- Merged PRs in scope (not re-opened here): `#2232`, `#2242`, `#2243`, `#2244`.
