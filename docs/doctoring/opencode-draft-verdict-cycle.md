# OpenCode draft-verdict chicken-and-egg repair

Date: 2026-09-01
Repository: `ContextualWisdomLab/.github`
Original owner PR: #1568
Protected base at reconciliation: `main@b4f7b082536d2be8dceab0a40a484161b50e5acd`

## Root cause

The required `opencode-review` workflow polled for an exact-head OpenCode verdict even when a pull request was a draft. The central scheduler intentionally does not dispatch ordinary review work for a draft unless an explicit agent-review path is requested. That created a self-hosting cycle: the required check waited for a verdict that the same governance system intentionally would not produce.

A second edge existed when a ready PR was converted back to draft while a poll was already running. Without a `converted_to_draft` trigger, no fresh PR-scoped run existed to cancel the stale poll. After adding that trigger, the request-review step also needed its own draft early exit so the replacement run could not fetch Reviews API evidence, exchange an OIDC token, or dispatch scheduler work before the later verdict step noticed draft state.

## Repair

- Add `converted_to_draft` to the `pull_request_target` trigger set.
- Both the request-review and required-verdict polling steps first make one unconditional, authoritative `gh api` live PR lookup (added after the initial fix, per Devin Review on this PR: a stale event-payload `PR_DRAFT`/head cannot be trusted on its own) and fail closed on a lookup error or an exact-head mismatch. Only after that live lookup confirms the PR is still draft on the live exact head does each step exit -- before any *further* GitHub API call or token exchange.
- Preserve `ready_for_review` behavior and the separate explicit marker-backed draft-review path.
- Keep `cancel-in-progress: true` concurrency behavior, now scoped by exact head SHA in addition to PR number (see "Head-scoped concurrency" below) so the converted-to-draft event still replaces a stale same-head poll.

Executable regressions cover the trigger, the request-step and verdict-step live-state-then-exit exemptions, closed-event precedence, moved-head fail-closed behavior, and unchanged non-draft behavior.

## Head-scoped concurrency and live closed-state validation (second Devin Review round)

Devin Review found two further defects once the live head/draft lookup above landed:

1. **Stale runs could cancel the current check.** The concurrency group was keyed only by repository and PR number. GitHub cancels whichever run is currently active in a group when a new one starts -- it has no notion of "older" or "newer" -- so a delayed, out-of-order run for an *older* head (e.g. a `synchronize` webhook delivered late under the org's saturated Actions queue) could cancel the *newer*, authoritative head's still-valid run before that older run's own live-head check ever had a chance to reject it. Fixed by also scoping the group by `github.event.pull_request.head.sha`: different heads no longer share a cancellation domain, while events for the exact same head (a `converted_to_draft`/`ready_for_review` transition, a `synchronize` retry) still do, which is what lets `converted_to_draft` retire an active same-head verdict poll.
2. **A delayed non-closed event ignored a live-closed PR.** `live_pr` only ever extracted `head` and `draft`; a stale `synchronize`/`ready_for_review`/etc. event arriving after the PR was actually closed had no way to notice and could still fetch the receipt-gate helper, exchange an OIDC token, dispatch a scheduler wake, or poll the Reviews API indefinitely. Both admission blocks now also extract and validate live `state`, exiting before any of that when it is `"closed"` -- mirroring the pre-existing `PR_ACTION == "closed"` event-level short-circuit, but driven by live API truth instead of the (possibly stale) event payload. A missing, null, non-string, or otherwise unrecognized `state` value fails closed rather than being treated as open, matching the existing `live_head`/`live_draft` validation style.

Executable regressions: a structural contract test pins the concurrency group's head-SHA scoping; step-body regressions cover a stale non-closed event against a live-closed PR (for both admission steps), live-closed state taking precedence over a stale live-draft flag, and each invalid `state` shape (missing/null/non-string/unexpected value) failing closed.

## Superseded-run cleanup for legitimate new commits (third Devin Review round)

Head-scoping the concurrency group above fixed the wrong-direction cancellation, but Devin Review found it also disabled a *legitimate* one: a genuine new commit (`synchronize`, head A -> B) no longer shares a concurrency group with head A's now-obsolete run, so nothing cancels it anymore. That older run's own live-head check ran once, before it entered the unbounded Reviews API wait loop, which never re-validates the head on later iterations -- left alone, it would occupy a hosted runner polling for a verdict OpenCode will never produce for that head, until GitHub's own per-job ceiling.

Fixed by adding a dedicated `cancel-superseded-opencode-review-runs` job, scoped to `synchronize` events, mirroring the already-established live-head-validated cleanup pattern in `strix.yml`'s own `cancel-superseded-pr-runs` job (and `noema-review.yml`'s in-job equivalent): it lists this PR's other active `Required OpenCode Review` runs (matched by workflow name/event plus a display-title or `pull_requests[]` PR-number match), excludes the currently-executing run and any run already on the live head, and cancels the rest -- re-verifying the live head immediately before both the listing pass and each individual cancellation, so a delayed/stale invocation of this same cleanup job cannot itself wrongly cancel a still-authoritative run.

Executable regressions: the embedded run-selection `jq` filter is extracted and executed against synthetic `workflow_runs` payloads (mirroring how `runtime_verdict()` already exercises the required-verdict filter), covering selection of a genuinely superseded older-head run, exclusion of a current-head run, exclusion of the cleanup job's own run, exclusion of a different PR, exclusion of a differently-named/triggered run, and matching via `pull_requests[]` metadata when `display_title` never rendered the head suffix; a structural test pins the job's `synchronize`-only trigger and `actions: write` permission.

## Reconciliation

The original branch diverged while unrelated protected-main repairs landed, including the Noema transport repair and the `graphql-core` security update. The branch is reconciled with current protected `main` through a normal two-parent merge commit; no force push or destructive rebase is used. Newer protected-main documentation is retained rather than replaced with stale branch copies. The concurrent review-event scheduler wake regression is retained in a dedicated regression file.

## Governance boundary

This repair removes an impossible required-check dependency; it does not weaken exact-head review requirements for non-draft PRs, fabricate review evidence, self-approve, suppress security findings, or change branch-protection thresholds. The separate repository-wide scheduler coverage repair is tracked on #1572.
