# Doctoring record: Actions queue remeasurement after #2232/#2233/#2235/#2236 (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** After the coalesce-tick observability and fail-open repairs
  (`#2232`, `#2233`) plus the same-day Strix/Noema evidence-binding merges
  (`#2235`, `#2236`), remeasure org Actions queue depth, the concurrent-job
  ceiling signal, and whether the five-minute coalesce tick now produces run
  records under saturation.
- **Decision record:** none — diagnostic remeasurement only; does not authorize
  plan-tier changes or further workflow edits by itself.
- **Measured at:** `2026-09-17T13:11:09Z`–`13:16:06Z` (UTC), via REST
  (`gh api`), against the live `ContextualWisdomLab` organization.

## Merge timeline (prerequisite)

| PR | Merged (UTC) | Head (short) | Title |
|---|---|---|---|
| `#2232` | `2026-09-17T10:33:07Z` | `b49641744ed6` | step-scope coalesce tick gate so schedule produces run records |
| `#2233` | `2026-09-17T10:35:23Z` | `d35788d73ab5` | fail-open coalesce when tick has not completed recently |
| `#2235` | `2026-09-17T12:06:56Z` | `130ce425f74c` | Strix: bind findings/remediation claims to authenticated evidence |
| `#2236` | `2026-09-17T12:53:17Z` | `4fda7f504e58` | Noema: bounded transport-capacity re-dispatch |

Protected `main` at measurement: `4fda7f504e58` (`#2236`).

## 1. Org Actions queue depth

Full census of all **66** non-archived, non-fork repositories
(`orgs/ContextualWisdomLab/repos`), summing
`actions/runs?status=in_progress|queued&per_page=1` → `.total_count`:

| Metric | Value |
|---|---|
| Org-wide workflow runs `in_progress` (sum) | **48** |
| Org-wide workflow runs `queued` (sum) | **1,911** |
| `.github` alone | `in_progress=10`, `queued=342`–`343` |
| Open PRs org-wide (`search/issues` `is:pr is:open`) | **4,288** |
| `.github` schedule runs currently `queued` | **15** |

Top queued repositories at the same sample:

| Repository | `in_progress` | `queued` |
|---|---|---|
| `.github` | 10 | 342 |
| `codec-carver` | 11 | 131 |
| `fast-mlsirm` | 3 | 131 |
| `late-life-anxiety-reanalysis` | 0 | 121 |
| `newsdom-api` | 5 | 121 |
| `pg-erd-cloud` | 1 | 114 |
| `appguardrail` | 4 | 112 |
| `contextual-orchestrator` | 1 | 112 |
| `clearfolio` | 2 | 108 |

**Reading:** the backlog shape is unchanged from the 2026-09-03 ceiling diagnosis
(`docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`): single- to
low-double-digit `in_progress` against four-digit `queued` org-wide. The
coalesce/fail-open repairs did not drain the queue; they were never expected to.
Compared with that earlier 3-repo snapshot (`.github` 1,877 queued alone),
`.github`'s own queued count is lower (~342), but the org-wide sum remains
~1.9k with thousands of open PRs still feeding required workflows.

## 2. Concurrent-job ceiling signal

GitHub still does not expose the org plan concurrent-job quota through REST.
This remeasurement therefore corroborates the previously recorded **~60**
plan-level ceiling with live occupancy proxies:

| Proxy | Value | Notes |
|---|---|---|
| Prior primary evidence | ~58–60 / 60 | User-observed billing UI, 2026-09-03 (same ceiling doc) |
| Org-wide runs `in_progress` | 48 / 66 repos | Run-level proxy; one run may hold multiple jobs |
| Jobs `in_progress` in 15 busiest repos | **42** | Sampled `runs?status=in_progress` → per-run `/jobs` |
| Hosted org runners API | `total_count=0` | No self-hosted pool; hosted plan quota is the ceiling |

The occupancy band (mid-40s jobs/runs concurrently active while ~1.9k runs sit
`queued`) remains the signature of a hard org-wide concurrent-job ceiling, not
of a per-repository workflow defect. No billing-UI re-read was available to this
session; the **60** figure is carried forward from the prior primary evidence,
not independently re-derived from Settings → Actions.

## 3. Coalesce tick run records since `#2232`

Workflow: `.github/workflows/opencode-review-coalesce-tick.yml` (id `360129488`),
cron `*/5 * * * *`, concurrency group `opencode-review-coalesce-tick` with
`cancel-in-progress: false`. Repo variable
`OPENCODE_REVIEW_COALESCE_ENABLED=false` (coalescing still inert by design).

| Observation | Evidence |
|---|---|
| Workflow `runs` total | `total_count=2` |
| Pre-`#2232` sample | `35191169833` at `2026-09-17T06:44:23Z`, `completed`/`skipped`, job skipped immediately (job-level gate era or equivalent) |
| Post-`#2232` sample | **`35219385415`** at `2026-09-17T12:07:50Z`, still `status=queued` at `13:16Z` |
| Post-merge job shape | Job `coalesce-tick` is `status=queued` (waiting for a runner), **not** immediately job-skipped — proves the step-scope gate admits the job into the runner queue |
| Flag still off | `vars.OPENCODE_REVIEW_COALESCE_ENABLED=false` → when the job eventually runs, the first step exits inert and remaining steps stay skipped |
| Schedule still enqueueing generally | `.github` `event=schedule&status=queued` → 15 runs (Daily Review Recovery, PR Auto Rebase, Required PR Review Merge Scheduler, this tick, …) |

**Reading relative to `docs/doctoring/actions-schedule-run-records-20260917.md`:**
that earlier record measured `total_count=0` for this workflow while the gate was
job-scoped. After `#2232`, at least one schedule run record exists and is sitting
in the same org admission backlog as every other schedule job. Only one post-merge
tick run is present as of this sample (created ~94 minutes after `#2232` merged);
the workflow concurrency group (at most one active + one pending, no cancel of
in-flight) plus multi-hour runner wait explains why the five-minute cron does not
accumulate unbounded stacked run records while the first tick remains `queued`.

`#2233`'s scheduler fail-open path is not exercised while the flag is `false`
(coalescing disabled → dispatch does not wait on tick completion). It remains
the safety net for the day the flag is flipped on under the same saturation.

`#2235` / `#2236` are evidence-binding / transport repairs; they do not change
queue depth or tick observability. They are listed here only because this
remeasurement was gated on all four merges landing.

## What this does / does not decide

- **Does confirm:** step-scoped coalesce tick observability works under live
  saturation (run + job enter `queued` instead of vanishing).
- **Does confirm:** org queue remains ceiling-bound (~48 concurrent runs /
  ~42 sampled concurrent jobs vs ~1.9k queued).
- **Does not:** raise the plan tier, enable `OPENCODE_REVIEW_COALESCE_ENABLED`,
  or claim the backlog is draining.
- **Still owner-only:** verify the exact concurrent-job quota on the org
  Actions/Billing UI if the ~60 figure must be re-attested for a purchase
  decision.

## Audit trail

- REST census script output: `/tmp/cwl-queue-census.json` (66-repo
  `in_progress`/`queued` totals; ephemeral local cache for this session).
- `repos/ContextualWisdomLab/.github/actions/workflows/opencode-review-coalesce-tick.yml/runs`
- `repos/ContextualWisdomLab/.github/actions/runs/35219385415` (+ `/jobs`)
- `repos/ContextualWisdomLab/.github/actions/variables/OPENCODE_REVIEW_COALESCE_ENABLED`
- Prior related records:
  `docs/doctoring/actions-schedule-run-records-20260917.md`,
  `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md`,
  `docs/doctoring/actions-capacity-root-cause-20260917.md`
