# Doctoring record: missed OpenCode re-dispatch after coalesce-tick gap (2026-09-17)

- **Date:** 2026-09-17
- **Subject:** Org-wide open PRs whose current head was pushed while
  `OPENCODE_REVIEW_COALESCE_ENABLED=true` (until `2026-09-17T04:21:48Z`) and the
  coalesce tick produced no successful dispatch runs; one-shot recovery for any
  exact head that still lacked an `opencode-review` `repository_dispatch`.
- **Decision record:** none — discovery + one-shot re-dispatch evidence only.
- **PR:** this commit's pull request.

## Window and mechanism

| Fact | Evidence |
|---|---|
| Coalesce flag off at | `OPENCODE_REVIEW_COALESCE_ENABLED=false`, updated `2026-09-17T04:21:48Z` |
| Miss window | `2026-09-17T01:48:00Z` .. `2026-09-17T04:21:00Z` (synchronize relied on coalesce tick) |
| Coalesce tick scope | `draft:false` org search; invokes `pr_review_merge_scheduler.py` → `dispatch_opencode_review()` → `event_type=opencode-review` on `ContextualWisdomLab/.github` |
| Prior related records | `docs/doctoring/coalesce-tick-inert-runner-queue-20260917.md`, `docs/doctoring/actions-schedule-run-records-20260917.md` |

## Discovery (GraphQL-first)

Cached under `/tmp/missed-opencode-*.json`:

| Artifact | Contents |
|---|---|
| `/tmp/missed-opencode-repos.json` | 79 non-archived org repositories |
| `/tmp/missed-opencode-candidates.json` | 44 open PRs whose current head commit `pushedDate` fell in the window |
| `/tmp/missed-opencode-ready-dispatch-audit.json` | Exact-SHA match against central `opencode-review-dispatch.yml` runs for the 8 non-draft candidates |
| `/tmp/missed-opencode-redispatch-result.json` | Re-dispatch outcome |
| `/tmp/missed-opencode-report.json` | Acceptance counts |

`pull_request_target` placeholder checks named `opencode-review` were **not** treated
as dispatch evidence. Only central `repository_dispatch` runs whose display title
contains `owner/repo#N@<40-char-sha>` count.

## Counts

| Metric | Value |
|---|---|
| Candidates (any draft state, window head) | **44** |
| Ready (`draft:false`, coalesce-tick scope) | **8** |
| Already had exact-SHA OpenCode Review Dispatch | **7** |
| Re-dispatched | **1** |
| Errors | **0** |
| Draft candidates (tick searches `draft:false`; not redispatched) | **36** |

## Ready heads

| Repo#PR | Head SHA | Action |
|---|---|---|
| `ContextualWisdomLab/appguardrail#1234` | `ca3c3634017a520ecc7bf3f59dc14909ba7a8424` | skipped — dispatch runs `35241486768` (queued), `35224607158` (cancelled) |
| `ContextualWisdomLab/argos#632` | `57a0548f0e442861f5a75a45f4a7db78b61b4e62` | **re-dispatched** → run `35268340425` |
| `ContextualWisdomLab/clearfolio#592` | `490307d00e5fc0890c83413da426317a44759df1` | skipped — dispatch run `35228993696` |
| `ContextualWisdomLab/html4tree#722` | `2c60d4013d606014b74b5f9ee8708ec91085fa47` | skipped — dispatch run `35239331445` |
| `ContextualWisdomLab/html4tree#723` | `5e374b1909089e38d478a053827478a94021e6f9` | skipped — dispatch run `35239417856` |
| `ContextualWisdomLab/html4tree#721` | `9bc3568b12d9e9267d5341b703d2d6c1bcd74c06` | skipped — dispatch run `35237634340` |
| `ContextualWisdomLab/OriginWeave#229` | `c7b7b0df9f0026f8c3f5ec546203c92d795bef74` | skipped — dispatch runs `35236887156`, `35225476687` |
| `ContextualWisdomLab/pg-erd-cloud#1152` | `43b55db88322f61c193b46b8eb6d2fc9c763f19d` | skipped — dispatch run `35239817421` |

## Re-dispatch detail (`argos#632`)

- Pre-check: no central `OpenCode Review Dispatch …@57a0548f…` run existed (older
  dispatches for `#632` targeted different SHAs `8214e031…` / `3141a6f8…`).
- Path: `POST repos/ContextualWisdomLab/.github/dispatches` with
  `event_type=opencode-review` and the same `client_payload` fields as
  `scripts/ci/pr_review_merge_scheduler_core.py::dispatch_opencode_review`
  (coalesce-tick / merge-scheduler terminal step). `argos` is absent from
  `OPENCODE_REPOSITORY_DISPATCH_TARGETS`, so a cross-repo `merge-scheduler`
  `repository_dispatch` would fail the allowlist; the scheduler's own OpenCode
  event does not use that allowlist.
- Live head revalidated immediately before POST; no force-push; coalesce flag
  untouched; no merge/auto-merge/branch-update.
- Resulting run: [35268340425](https://github.com/ContextualWisdomLab/.github/actions/runs/35268340425)
  (`queued` at enqueue). Post-check: exactly one matching run for that SHA.

## Constraints observed

- No duplicate dispatch for any head that already had an exact-SHA run.
- No force-push, self-approve, or `OPENCODE_REVIEW_COALESCE_ENABLED` change.
- Private repos: none among the 8 ready candidates; draft private inventory was
  empty in this window sample.
- REST 403 / rate-limit: backoff with exponential sleep; GraphQL used for org/PR
  enumeration.
