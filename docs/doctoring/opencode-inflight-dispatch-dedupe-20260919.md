# Doctoring: OpenCode same-head in-flight dispatch dedupe (2026-09-19)

- **Date:** 2026-09-19
- **Incident:** ContextualWisdomLab/pg-erd-cloud Required OpenCode Review run
  `35412595263` job `105868602312` (PR #1183 head `9a759df24e8b714348ac2d240491f74ee3fc852d`,
  workflow pin `64aa08d7…`). Job created `08:30:15Z`, started `12:41:37Z`, completed
  `12:41:46Z` → **4h11m22s queue / ~9s execution**. Steps: review dispatch succeeded
  `12:41:39–43`, then fail-closed `12:41:45` with “No APPROVED or CHANGES_REQUESTED from
  opencode-agent on the current head… will rerun this failed job after publishing an
  authenticated exact-head verdict.” Same handshake as appguardrail#1247.
- **Shared owner:** `ContextualWisdomLab/.github` (`opencode-review.yml` +
  `opencode-review-dispatch.yml`). Callers are org ruleset `18156473` targets (all default
  branches except documented exclusions) — do not patch leaf repos.

## What is *not* broken

- Fail-closed without a formal exact-head verdict (intentional; must not become success).
- Wake via `required_run_id` + `path=.github/workflows/opencode-review.yml` +
  `event=pull_request_target` + exact `head_sha` (live incident run matches; not an
  org-ruleset path mismatch).
- Releasing the runner instead of polling the multi-hour model
  (`docs/pr-review-and-merge-procedure.md`).

## What *is* broken under saturation

1. **Duplicate same-head `repository_dispatch`.** Every new required admission after a
   completed fail-closed handshake posts another dispatch when the receipt is still
   missing. Dispatch concurrency is `opencode-review-dispatch-${repo}-${pr}` with
   `cancel-in-progress: true`, so the new event **cancels** the prior queued/running
   review for that PR — including a multi-hour review that had not yet woken the
   required check.
2. **Queue amplification.** Each cancelled review + each required job that waits hours
   only to spend 9s on dispatch+fail burns org runner admission without advancing a
   verdict (measurement pattern in `docs/doctoring/actions-capacity-root-cause-20260917.md`).

The scheduler already skips with `already_running` via `active_opencode_run_refs`; the
**required** entrypoint did not.

## Minimal fix

- Add `scripts/ci/opencode_inflight_dispatch_gate.py` — exact-equality match central
  `repository_dispatch` runs whose `display_title` is
  `OpenCode Review Dispatch {repo}#{pr}@{40-hex head}`.
- Inspect every GitHub-defined nonterminal workflow status: `queued`, `in_progress`,
  `requested`, `waiting`, and `pending`; paginate every result page. The REST
  contract caps `per_page` at 100, so first-page admission is not complete evidence.
- In `opencode-review.yml` “Request current-head OpenCode review execution”, after OIDC
  app-token exchange and before `dispatches` POST: if gate returns `present`, skip the
  POST; always continue to the fail-closed verdict step (no success without receipt).
- Tests: `tests/test_opencode_inflight_dispatch_gate.py` plus updates to
  `tests/test_opencode_required_verdict_regression.py`.

## Forbidden

- Marking the required check success without an `opencode-agent` /
  `opencode-agent[bot]` / formal receipt-gate APPROVED or CHANGES_REQUESTED on the
  exact head.
- Weakening wake identity checks or dropping `required_run_id` binding.
- Per-leaf “just re-run the job” as the repair.

## Before / after (measurement intent)

| Metric | Before (incident) | After (expected) |
|--------|-------------------|------------------|
| Same-head duplicate dispatch while prior queued/running | Allowed (cancels prior) | Skipped (`present`) |
| Required job still fail-closed without verdict | Yes | Yes (unchanged) |
| Wake after formal receipt | `rerun-failed-jobs` on `required_run_id` | Unchanged |
| Queue waste class | Hours → 9s fail → re-dispatch cancel loop | Hours → 9s fail **without** cancelling in-flight review |

## Related

- appguardrail#1247 tracker: `TRACK-appguardrail-1247.md`
- Capacity root cause: `docs/doctoring/actions-capacity-root-cause-20260917.md`
- CodeQL wake-once parallel (not this PR): `.github#2051`


## Exact-identity follow-up

The initial implementation admitted four false boundaries:

- repository components containing repeated dots or ending in a dot;
- a run title with arbitrary bytes after the 40-hex head;
- only `queued` and `in_progress`, omitting GitHub's active `requested`,
  `waiting`, and `pending` states;
- only the first 100 runs during the saturation incident class this gate exists to fix.

RED commit `5d1ab119d4c0140f68dfef555d2818ac96e0616c` records all four
contracts. GREEN commit `e8b6570b8c9c5930178717c326fc20583e37dcab`
uses canonical repository components, exact title equality, GitHub's complete
nonterminal status set, and `gh api --paginate --slurp`.

Exact remote verification compiled source and tests (**2/2**) and passed
**10/10** focused contract assertions. Full pytest is not claimed because the
isolated verifier does not provide pytest; fresh hosted exact-head Checks remain
mandatory.

## Authoritative source

GitHub. (2026). *REST API endpoints for workflow runs: List workflow runs for a
repository*. Retrieved September 19, 2026, from
https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28#list-workflow-runs-for-a-repository
