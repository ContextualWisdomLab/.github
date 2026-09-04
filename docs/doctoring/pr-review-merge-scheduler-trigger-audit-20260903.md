# Doctoring record: pr-review-merge-scheduler.yml's "fires at every step" pattern is by-design, not a bug (2026-09-03)

- **Date:** 2026-09-03
- **Subject:** the user directly observed the scheduler workflow firing repeatedly ("왜 각 모든 단계마다 Trigger
  되고 있죠?") after live evidence surfaced today of severe org-wide Actions thrashing (near-zero completion
  rate; a peer's independent measurement found ~3 jobs in_progress against ~9,368 queued org-wide, and this
  session independently confirmed 10 in_progress / 1,713 queued / zero successes in the last 20 runs for
  `.github` alone). Directed to trace and fix the workflow issues causing it, with bypass-merge explicitly
  authorized for this chicken-and-egg case.
- **Decision record:** none in `docs/adr/` — negative/confirmatory finding for this specific file, cross-
  referenced against a real, separate fix a peer session applied to a different file in the same
  investigation.
- **PR:** `ContextualWisdomLab/.github#1763`.

## Method

Fetched `pr-review-merge-scheduler.yml` fresh from `raw.githubusercontent.com` at commit `8c08583`
(the file's own last-modifying commit on `main` as of this writing; re-verify against a fresh
`gh api "repos/ContextualWisdomLab/.github/commits?path=.github/workflows/pr-review-merge-scheduler.yml&sha=main"`
call if the file has changed since) and read its full trigger
surface, concurrency configuration, and `scan-pr-queue` job's `if:` guard. Cross-referenced against a peer
session's concrete evidence (PR `ContextualWisdomLab/naruon#1741`: 90 total workflow runs on that PR's branch, 10 of them
"Required PR Review Merge Scheduler"). Traced the `rerun-failed-jobs` mechanism referenced in this file's
`workflow_run` listener back to its source in `opencode-review-dispatch.yml` to determine whether it is a
chronic, repeated re-trigger source or a bounded, once-per-cycle event.

## Result: the trigger surface is legitimately event-reactive, not redundant

`pr-review-merge-scheduler.yml`'s `on:` block listens for: `push` (protected branches), `pull_request_target`
(6 types), `pull_request_review` (2 types), `workflow_run` on exactly two named workflows ("Required
OpenCode Review", "Strix Security Scan") with `types: [completed]`, two `schedule` crons (offset by 30
minutes to avoid collision, each independently justified in the file's own comments for a specific coverage
gap), `workflow_call`, and `repository_dispatch`. Every one of these represents a genuinely distinct,
actionable state change the scheduler exists to react to:

- A push (new commit) changes what the scheduler should evaluate.
- A review submission/dismissal changes approval state.
- "Required OpenCode Review" completing is new information the scheduler needs to decide on branch
  updates/auto-merge — the scheduler cannot know a review landed without being told.
- "Strix Security Scan" completing is the same, for the security gate.
- The two schedule crons close real, already-documented coverage gaps (this repository's own PR queue has
  no other periodic fallback since `org-queue-sweep` explicitly excludes `ContextualWisdomLab/.github`; a
  PR whose last required check to go green has no dedicated `workflow_run` listener otherwise stalls with
  no re-wake at all).

The `rerun-failed-jobs` call inside `opencode-review-dispatch.yml`'s "Wake exact-head required OpenCode
workflow" step (which would itself re-trigger the scheduler via `workflow_run` on completion) is gated
behind `steps.formal_review_receipt.outcome == 'success'` and only fires when the required run is
`completed`+`failure` — a bounded, once-per-review-cycle continuation of an already-published receipt, not
a chronic re-fire loop.

**PR `ContextualWisdomLab/naruon#1741`'s 10 scheduler runs are consistent with this legitimate surface** (push(es) + review
submission(s) + OpenCode completing + Strix completing + the two hourly/30-minute heartbeats over the PR's
open lifetime), not evidence of a bug in this file's trigger design.

## The actual mechanism behind the observed thrashing is elsewhere, and already being fixed

`cancel-in-progress` in this file is `true` only for `pull_request_target`, `pull_request_review`,
`repository_dispatch`, and the no-PR-number `workflow_run` branch — every one of which represents a
genuinely new triggering event that supersedes the scheduler's prior, now-stale, in-flight evaluation, for
branch-specific reasons: a new `pull_request_target` event means a push or review-state change already
invalidated whatever the prior run was computing; a new `pull_request_review` means an approval/change-request
just arrived; a new `repository_dispatch` is an explicit, deliberate re-invocation (a manual retry or a
cross-repo caller); and the no-PR-number `workflow_run` branch fires only for events with no associated PR
(so there is nothing PR-specific yet to preserve). `workflow_run` itself — CodeRabbit correctly noted — is a
workflow-completion event, not a direct user action; grouping it under "user-driven" was imprecise. It is
explicitly `false` for the
PR-associated `workflow_run` branch (OpenCode/Strix completing), so those queue rather than evict an
in-progress run. This matches the same correctly-scoped pattern already confirmed for `strix.yml`,
`opencode-review.yml`, and `noema-review.yml` in `docs/doctoring/item13-stale-head-cancellation-audit-20260903.md`
(a separate, not-yet-merged PR as of this writing — see `ContextualWisdomLab/.github#1760`; that doc will
not exist on this branch until it merges) — **no self-defeating cancellation bug was found in this file.**

A peer session, working the same live-evidence investigation, found and fixed a real bug in a related
file, in two rounds (`ContextualWisdomLab/.github#1661`): `current-head-run-coalescer.yml` (the mechanism
specifically meant to prune stale-SHA queued runs) carried `cancel-in-progress: true` on its own PR-scoped
concurrency group — but under today's unusually high push volume from four concurrent agent sessions, each
new push cancelled the coalescer's own prior in-flight attempt before it could get a runner, so it never
actually executed for a busy PR. The first fix (commit `c0dc46b`, flipping `cancel-in-progress` to `false`)
was itself caught as incomplete by Devin Review: a plain `cancel-in-progress: false` only protects a
*running* job — GitHub concurrency groups still silently evict a *pending* (queued) run the instant another
run enters the same group, regardless of `cancel-in-progress`, which is exactly the failure mode that had
been observed (a required-review check sat stuck queued with the coalescer never once executing for it).
The complete fix (commit `12d5735`) adds `queue: max`, a GitHub Actions concurrency feature — an
already-precedented pattern in this repo (`agent-mention-router.yml`) — that retains up to 100 pending runs
instead of evicting all but the latest. **Precision on `queue: max`'s own limits (CodeRabbit correctly
caught the original wording overclaiming this):** the 100-pending-run retention is a hard cap, not
unlimited — a burst exceeding it can still evict overflow arrivals; and GitHub does not guarantee strict
FIFO dispatch order for the retained runs (ordering is based on when each run started waiting on the group,
not when it was originally triggered, and that too is not a hard guarantee). Neither limit changes the
verdict for the specific incident this fix responds to (PR `#1741`'s push volume was far below the 100-run
cap), but "runs them in order" should not be read as a general ordering guarantee beyond that — see
`queue: max`'s own residual-gap note in `current-head-run-coalescer.yml` for the fuller caveat. Combined
with the coalescer script's own live-state re-fetch (confirmed safe for a surviving queued instance to run
later, since it never trusts the head SHA it was triggered with), that was a genuine, two-round
self-starvation bug, distinct from anything in this file, and is the more direct, evidence-backed
explanation for the observed churn than this workflow's trigger breadth.

**Conclusion:** forcing a change to this file's trigger surface (removing `workflow_run` listeners, say) on
the strength of the "fires at every step" observation would have traded real event-reactivity (the
scheduler promptly noticing a review or a security verdict landing) for a fix that does not address the
actual mechanism — consistent with this session's practice of not forcing a change that a real look shows
is not the right lever. Real, safe progress was made instead: PR `#1725` (the `dependency-review.yml`
fail-closed hardening this session's separate consolidation effort is blocked on) was found `mergeable_state:
behind` with most required checks already green and only a handful still queued; its branch was updated
(a normal, non-bypass maintenance action) to let its remaining checks proceed once runner capacity allows.

## Audit trail

- `docs/doctoring/item13-stale-head-cancellation-audit-20260903.md` — the sibling investigation this record
  extends, confirming the same "correctly scoped, not a bug" pattern for the other three central workflows.
- `docs/doctoring/actions-plan-concurrency-ceiling-20260903.md` — the underlying capacity finding this
  thrashing evidence corroborates rather than replaces.
- `ContextualWisdomLab/naruon#1741` — the concrete 10-run/90-total-run example cross-checked here.
- `ContextualWisdomLab/.github#1725` — the dependency-review consolidation prerequisite whose branch was
  updated as part of this investigation's concrete follow-through.
