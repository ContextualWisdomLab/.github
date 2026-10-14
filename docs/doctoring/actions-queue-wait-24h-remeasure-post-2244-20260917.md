# Doctoring record: Actions queue-wait remeasurement after #2228–#2230 job folding and #2231–#2244 coalesce/admission changes (2026-09-17)

- **Date:** 2026-09-17 (measurement window closed ~`20:15Z`)
- **Subject:** Re-measure org Actions queue depth and central/product queue-wait
  after the same-day job-folding merges (`#2228`, `#2230`) and the coalesce /
  admission series through `#2244`, and compare against the pre-/mid-merge
  doctoring baselines.
- **Decision record:** none — diagnostic only. Does **not** authorize plan-tier
  changes, workflow caps, disabling workflows, or flipping
  `OPENCODE_REVIEW_COALESCE_ENABLED`.
- **PR:** this commit's pull request.

## Merge window in scope

| PR | Merged (UTC) | Role |
|---|---|---|
| `#2228` | `2026-09-17T00:42:05Z` | fold same-trust-level jobs on OpenCode Review Dispatch |
| `#2230` | `2026-09-17T01:11:06Z` | fold `required-workflow-bootstrap` + `admit-current-head` |
| `#2231` | `2026-09-17T01:47:34Z` | push-burst coalescing (inert by default) |
| `#2232`–`#2233` | `10:33Z`–`10:35Z` | step-scope tick gate + fail-open |
| `#2237` | `13:23:24Z` | prior queue 24h remeasurement (pre-`#2242`) |
| `#2242` | `16:14:00Z` | skip inert coalesce ticks **before** runner admission |
| `#2244` | `17:18:55Z` | post-`#2242` live verify + re-enable criteria |

Best available post-settle window for this record: from `#2242` merge
(`16:14Z`) through measurement (`~20:15Z`) ≈ **4h**, embedded in a rolling
**~24h** sample that also covers the earlier folding/coalesce merges. Full
calendar 24h after `#2244` was not yet available at measurement time.

Referenced baselines (task aliases → files present in-tree):

- `docs/doctoring/actions-capacity-root-cause-20260917.md`
- `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`
- `docs/doctoring/actions-queue-24h-remeasurement-20260917.md` (mid-day, after
  `#2232`–`#2236`, before `#2242`)
- `docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md`
  (covers the “schedule-queue / admission levers” verification intent; no
  separate `schedule-queue-post-2242-admission-levers*` file existed at
  measurement time)

## Methodology

1. **Org census (batch REST, no polling loops):** for all 66 non-archived,
   non-fork `ContextualWisdomLab` repositories, read
   `actions/runs?status=in_progress|queued&per_page=1` → `.total_count`. Cache:
   `/tmp/queue-remeasure-census.json` (also copied as
   `queue-remeasure-census-final.json`).
2. **Central workflows on `.github`:** resolve by workflow filename, page up to
   24h of runs, and separately sample `status=queued` ages. Job-level
   admission = run `created_at` → first job `started_at` for runs that actually
   executed (≥1 job `success`/`failure`/`timed_out`/`in_progress`). Caches:
   `/tmp/queue-remeasure-detail.json`, `/tmp/queue-remeasure-joblevel.json`,
   `/tmp/queue-remeasure-queued-ages.json`.
3. **Product hourly callers:** `OriginWeave`, `Keyverse`,
   `contextual-orchestrator` (plus repo-level depth for `naruon`, `nonnest2`).
4. **Caveat on run-level `run_started_at`:** many cancelled-before-runner runs
   report near-zero `created→run_started_at`, so raw run-level p50 understates
   wait. Prefer **queued age** and **job-level admission** below.
5. **Rate limit:** REST core remaining stayed healthy (`≥4500`); 403 backoff
   prepared but not required. `OPENCODE_REVIEW_COALESCE_ENABLED` left
   **`false`** (read-only check).

## Before / after queue-wait table

### A. Org-wide depth (plan-ceiling signature)

| Snapshot | `in_progress` (sum) | `queued` (sum) | Notes |
|---|---|---|---|
| 2026-09-03 ceiling doc (3-repo sample) | 10 | 3,020 | `.github` alone queued **1,877** |
| 2026-09-17 `13:11Z`–`13:16Z` (`#2237` remasure) | **48** | **1,911** | 66-repo full census; open PRs **4,288** |
| **This remasure `20:07Z`** | **34** | **2,090** | 66-repo full census; open PRs **4,256** |

Top queued repos at `20:07Z`: `.github` 440, `contextual-orchestrator` 195,
`fast-mlsirm` 177, `newsdom-api` 151, `appguardrail` 149, `codec-carver` 131.

**Reading:** shape unchanged — low-double-digit concurrent runs vs ~2k queued.
Folding/coalesce did **not** drain the org backlog (and were not expected to).
`.github` queued rose vs mid-day (342 → 440) while org `in_progress` fell
(48 → 34), consistent with a hard ~60 concurrent-job plan ceiling still binding
(`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`).

### B. Central required / dispatch workflows (`.github`)

| Workflow | Mid-day `#2237` signal | This remasure (`~20:15Z`) | Delta |
|---|---|---|---|
| Org / `.github` depth | org q≈1911; `.github` q≈342 | org q=2090; `.github` q=440 | backlog **deeper** |
| `opencode-review-dispatch` queued now | (not broken out) | **100** queued; age p50 **2.5h** / p95 **11.3h** (sample includes stale >24h rows; max age **107h** from `2026-09-13`) | still multi-hour admission backlog |
| Dispatch job-level admission (executed, n=35) | root-cause saturated sample: **hours per `needs:` hop** on 4-job chain | admit p50/p95 **3.2h / 3.3h**; post-`#2242` admit p50 **3.1h** | first-job wait still ~3h; see folding note below |
| `opencode-review` queued ages (n=41) | — | p50 **1.5h** / p95 **5.6h** / max **6.9h** | multi-hour |
| `strix` / `noema-review` queued ages | — | both ~p50 **1.5h** / p95 **5.6h** | multi-hour; Noema sample also has a **712h** stale queued outlier (`2026-08-19`) |
| `pr-review-merge-scheduler` queued ages (n=19) | — | p50 **49m** / p95 **2.3h** | shorter than AI review class; still ceiling-bound |
| `.github` `event=schedule` queued | 15 | **14** | flat |
| Coalesce tick (`360129488`) | post-`#2232` inert tick **queued ~3.5h** (`35219385415`) | post-`#2242`: **`35249460935`** + **`35267797508`** both `completed`/`skipped` in **1s**; **0** queued now | **admission-skip fix holds**; second skipped tick observed |

### C. Job-folding effect on the dispatch chain

Root-cause baseline (`actions-capacity-root-cause-20260917.md`), saturated run
`34931908846`: four-job chain with **~13h36m** pure inter-job queue wait
(97.5% of wall time).

Post-`#2228` live samples (executed failures around `19:4x`–`19:5xZ`): chain is
`validate-pr-metadata` → `coverage-evidence` → `opencode-review` (folded hop
removed). When validate fails, dependents skip immediately → measured
inter-job wait ≈ **0**. First-job **admission** remains **~3.0–3.3h**.

So folding removed a **repeatable multi-hour hop** when the chain would have
continued, but does **not** remove the org admission wait before the first job
starts. No successful full review-target completion appeared in the newest
completed dispatch page at sample time (page was dominated by validate-time
failures after ~3h admit).

### D. Product hourly callers

| Caller | Repo queued / in_progress | Hourly workflow wait (24h sample) |
|---|---|---|
| `.github` `hourly-review-repair.yml` | **9** queued (age p50 **3.0h** / max **6.7h**); executed admit p50 **5.6h** (n=8) | schedule class still multi-hour |
| `OriginWeave` Hourly Product Development | q=10 / ip=0 | n=5; p95 age ~**2.9h** (queued-heavy) |
| `Keyverse` Hourly product development | q=1 / ip=0 | n=6; p95 age ~**4.9h** |
| `contextual-orchestrator` OpenCode hourly maintenance loop | q=195 / ip=1 | n=6; p95 age ~**1.8h** |
| `naruon` / `nonnest2` (depth only) | q=17 / 24 | no local `hourly*` workflow name match in sample |

## Coalesce / admission levers (residual)

| Lever | Status at measurement |
|---|---|
| `#2242` job-level `OPENCODE_REVIEW_COALESCE_ENABLED` gate | **Confirmed** on delivered ticks (1s skip) |
| Flag value | **`false`** (unchanged; this task did not flip it) |
| Re-enable should-have #4 (capacity headroom) from post-`#2242` verify doc | **Not met** — org queued ≈2.1k, `in_progress` ≈34 vs ~60 ceiling |
| Stale queued hygiene | Dispatch / Noema / scheduler show **multi-day** queued outliers; they inflate max ages and occupy admission attention without progressing |

## What this does / does not decide

- **Does confirm:** plan-ceiling backlog signature persists after folding +
  coalesce repairs; `#2242` prevented inert coalesce ticks from re-entering the
  runner queue; a second post-`#2242` skipped tick landed (`35267797508`).
- **Does confirm:** job folding shortens the dispatch `needs:` chain; remaining
  dominant cost for that class is **first-job admission (~3h)** under saturation,
  not model runtime.
- **Does not:** raise the plan tier, add concurrency caps, disable workflows, or
  enable `OPENCODE_REVIEW_COALESCE_ENABLED`.
- **No scheduler admission code change in this PR:** no new concrete admission
  bug was proven beyond what `#2242` already fixed. Residual blockers are
  plan-ceiling headroom and stale-queued hygiene, both owner/ops scope.

## Residual blockers (plan ceiling headroom)

1. **Org concurrent-job ceiling ~60** still binds (occupancy proxy mid-30s runs
   while ~2k sit queued). Raising the tier / adding a separate runner pool remains
   the only lever that lifts concurrent throughput.
2. **Open PR load (~4.2k)** continues to feed required workflows faster than the
   ceiling drains them.
3. **Coalesce re-enable** still blocked on capacity/fail-open acceptance per
   `docs/doctoring/coalesce-tick-post-2242-live-verify-20260917.md` §should-have.
4. **Stale queued runs** (dispatch max age 107h; Noema outlier 712h) should be
   inventoried and cancelled only with event-specific head evidence — not via an
   org-wide sweep (see `AGENTS.md` Actions queue procedure).

## Audit trail

- `/tmp/queue-remeasure-census.json` — 66-repo `in_progress`/`queued` census @
  `2026-09-17T20:07:05Z` (ip_sum=34, queued_sum=2090).
- `/tmp/queue-remeasure-detail.json` — central workflow 24h run samples @
  `~20:09Z`.
- `/tmp/queue-remeasure-joblevel.json` — job-level admission/inter-job samples @
  `~20:15Z`.
- `/tmp/queue-remeasure-queued-ages.json` — live queued-age percentiles @
  `~20:15Z`.
- Repo variable read:
  `repos/ContextualWisdomLab/.github/actions/variables/OPENCODE_REVIEW_COALESCE_ENABLED`
  → `false`.
- Coalesce runs: `35249460935`, `35267797508` (skipped 1s);
  `35219385415` (pre-`#2242` cancelled after long queue).
- Prior baselines listed in the Subject / merge tables above.
