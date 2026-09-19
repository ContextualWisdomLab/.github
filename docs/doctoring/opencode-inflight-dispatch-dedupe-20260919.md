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

- Add `scripts/ci/opencode_inflight_dispatch_gate.py` — title-match central
  `repository_dispatch` runs whose `display_title` is exactly
  `OpenCode Review Dispatch {repo}#{pr}@{40-hex head}` in `queued`/`in_progress`.
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
