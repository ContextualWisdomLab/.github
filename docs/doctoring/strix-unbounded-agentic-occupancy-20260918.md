# Doctoring record: unbounded Strix agentic occupancy held fast-mlsirm under the plan ceiling (2026-09-18)

- **Date:** 2026-09-18
- **Subject:** `ContextualWisdomLab/fast-mlsirm` Actions queue showed ~179–180
  `queued` runs against 1–2 `in_progress` while a single central Strix Security
  Scan occupied a hosted runner with no progress or job occupancy bound.
- **Decision records:** ADR-0034 (progress / admission occupancy, not elapsed
  inference); ADR-0030 (plan concurrent-job ceiling cannot be lifted by
  workflow consolidation); ADR-0028 principle (numeric bounds must be sourced
  from measurement, not invented — here applied to Strix occupancy, not the
  coalesce-tick max-age).

## Live holder (re-fetched)

| Field | Value |
|---|---|
| Run | [35263416380](https://github.com/ContextualWisdomLab/fast-mlsirm/actions/runs/35263416380) |
| Event | `pull_request_target` (required Strix path) |
| PR | fast-mlsirm#1988 @ `3211659557118354c61a8221119c0dc314f0c90b` |
| Run created / started | 2026-09-17T19:11:44Z (~10h wall at measurement) |
| Job | `strix` id `105414661161` |
| Labels | `ubuntu-24.04` (standard hosted; not larger / self-hosted) |
| Job started | 2026-09-18T03:52:48Z |
| Step holding | `Run Strix (quick)` since 2026-09-18T04:18:54Z |
| Concurrent sibling | CI run [35287625813](https://github.com/ContextualWisdomLab/fast-mlsirm/actions/runs/35287625813) (`push`, rust still in progress / python jobs cycling) |

Timeline split (why "10h" is not 10h of model work):

1. 19:11Z → ~23:00Z: run admitted; `admit-current-head` / `Detect changed scope`
   completed in seconds once they got runners.
2. ~23:00Z → 03:52Z: `strix` job waited for a runner under the org plan
   concurrent-job ceiling (~60; see
   [`actions-plan-concurrency-ceiling-20260903.md`](actions-plan-concurrency-ceiling-20260903.md)).
3. 03:52Z onward: setup + sidecar (~26m) then unbounded `Run Strix (quick)` with
   `STRIX_PROCESS_TIMEOUT_SECONDS=0`, `STRIX_TOTAL_TIMEOUT_SECONDS=0`,
   `LLM_STREAM_IDLE_TIMEOUT=0` (forced by `strix_timeout_compat.py`), and **no**
   job-level `timeout-minutes` (platform default 360m).

## Why concurrency looks like ~1 on a public repo

API sample at measurement (REST `actions/runs?status=`):

| Repository | `in_progress` | `queued` |
|---|---|---|
| `fast-mlsirm` | 1–2 | ~179–180 |
| `.github` | 17 | ~538 |
| `contextual-orchestrator` | 2 | ~151 |
| `naruon` | 0 | ~76 |

That shape matches the **org-wide plan concurrent-job ceiling**, not
per-repository Strix serialization and not a larger-runner pool:

- Central `strix.yml` concurrency group is
  `strix-security-scan-<repository>-<pr|push|run_id>` with
  `cancel-in-progress: true` — one Strix **per PR**, not one for the whole org.
- Holder labels are `ubuntu-24.04`; org self-hosted runners `total_count=0`.
- Other repos simultaneously hold double-digit `in_progress` counts, so
  fast-mlsirm is not uniquely capped at one slot by workflow design.
- Billing plan ceiling is not exposed on the Actions REST API (ADR-0030); the
  user-reported 58–60/60 figure remains in the 2026-09-03 doctoring record.

## Root defect in the central Strix path

`#1546` / `#1895` correctly removed **model-path** wall clocks (including the
reverted 900s `#1889` cap). The residual hole was treating that as "no bound
of any kind": an agentic scan with stream-idle forced to `0` and no job
occupancy release can hold a shared runner until the platform 360m kill while
hundreds of unrelated jobs stay `queued`.

Directive §8 still forbids converting elapsed inference into a model-failure
verdict. ADR-0034 names the allowed repairs: **progress (idle-socket)** and
**admission/occupancy release**, with expiry classified as occupancy — not as
"the model was too slow."

## Repair landed with this record

1. **Job `timeout-minutes: 180`** on the central `strix` job — occupancy
   release sourced from measured ~2h Strix occupancy
   (`startup-failure-and-strix-concurrency-20260904.md`) plus 50% large-repo
   margin under §8's >2h tolerance, still ≪ 360m platform. Required check name
   `strix` unchanged.
2. **`LLM_STREAM_IDLE_TIMEOUT=90`** in `strix_timeout_compat.py` — progress
   bound sourced from `#1884` run `34732993973` (8/10 dead-socket attempts at
   exactly 90.0s). Request / warm-up elapsed deadlines remain disabled
   (`LLM_TIMEOUT=0`, `STRIX_PROCESS/TOTAL_TIMEOUT_SECONDS=0`).
3. **ADR-0034** recorded on `main` so the next change cites the occupancy
   decision rather than re-litigating §8.

## Duplicate "Detect changed scope" contexts (separate, non-blocking)

On the hung head, four distinct workflow runs each published a check named
`Detect changed scope` (Strix, and peer required workflows). That multiplies
admission slots under the same ceiling. Reduction without weakening gates is
already scoped by open
[ContextualWisdomLab/.github#1962](https://github.com/ContextualWisdomLab/.github/pull/1962)
(fold admit + changed-scope into one metadata job per workflow; keep required
`strix` / scan job names). Do not rename required contexts in this occupancy
PR.

## Audit trail

- REST: `repos/ContextualWisdomLab/fast-mlsirm/actions/runs/35263416380` and
  `/jobs` (job `105414661161`).
- REST queue samples: `actions/runs?status=queued|in_progress` on
  `fast-mlsirm`, `.github`, `contextual-orchestrator`, `naruon`, `OriginWeave`.
- OriginWeave completed-scan sample: run `35178432177` job `105140349882`
  (~78.1m job / ~31.1m `Run Strix (quick)`).
- `#1884` / run `34732993973` sidecar evidence cited in ADR-0034.
- `docs/product-goal-directive.md` §8; `#1889` / `#1895`; `#1546`.
