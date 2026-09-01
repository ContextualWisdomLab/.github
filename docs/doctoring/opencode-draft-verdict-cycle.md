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
- Keep the existing PR-scoped `cancel-in-progress: true` concurrency behavior so the converted-to-draft event replaces a stale non-draft poll.

Executable regressions cover the trigger, the request-step and verdict-step live-state-then-exit exemptions, closed-event precedence, moved-head fail-closed behavior, and unchanged non-draft behavior.

## Reconciliation

The original branch diverged while unrelated protected-main repairs landed, including the Noema transport repair and the `graphql-core` security update. The branch is reconciled with current protected `main` through a normal two-parent merge commit; no force push or destructive rebase is used. Newer protected-main documentation is retained rather than replaced with stale branch copies. The concurrent review-event scheduler wake regression is retained in a dedicated regression file.

## Governance boundary

This repair removes an impossible required-check dependency; it does not weaken exact-head review requirements for non-draft PRs, fabricate review evidence, self-approve, suppress security findings, or change branch-protection thresholds. The separate repository-wide scheduler coverage repair is tracked on #1572.
