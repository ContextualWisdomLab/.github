# Org-queue-sweep review-dispatch rotation

## Problem

`org-queue-sweep` in `pr-review-merge-scheduler.yml` walks every organization
repository once per 15-minute tick and consumes one shared, organization-wide
review-dispatch budget (`ORG_SWEEP_REVIEW_DISPATCH_LIMIT`, default `1`) across
that entire walk. The walk order came from a single `gh api
/orgs/{org}/repos` call with no explicit sort, so it was effectively fixed
across ticks. A repository early in that fixed order always consumed the
single available dispatch, so every later repository's ready, all-green,
zero-open-thread pull requests never reached the OpenCode review dispatch
through the sweep fallback path — indefinitely, not just for one tick.

`ContextualWisdomLab/.github#1219` recorded this with direct evidence from a
RankWeave sweep run: PRs #36, #40, and #41 all reported `review dispatch limit
reached` in the same run where the org-wide budget was already `1/1` before
RankWeave's own turn.

## Decision

Rotate the sweep's repository walk order by a wall-clock rotation tick
(`$(date -u +%s) / 900`, one tick per 900 seconds) before applying the
unchanged organization-wide budget. `rotation_offset = rotation_tick %
repository_count`; the walk starts at that offset and wraps. This spreads the
exact same total per-tick dispatch budget across repositories over successive
sweep ticks instead of raising it.

An earlier version of this fix derived the rotation index from
`github.run_number` instead. PR review (`ContextualWisdomLab/.github#1220`,
Devin) correctly flagged that `run_number` increments on every trigger of
this workflow — push, `pull_request_target`, `pull_request_review`,
`workflow_run` — not only the `*/15` sweep schedule, so it could not give the
"bounded by `repository_count` ticks" guarantee a rotation is meant to
provide: two consecutive sweep runs could see `run_number` jump by more than
one, or (in a busy-workflow edge case) by an exact multiple of
`repository_count`, silently skipping or repeating offsets. Wall-clock time
does not have that dependency: a rotation tick advances by exactly one every
15 minutes no matter how many other events fired this workflow in between,
which is what the `repository_count`-tick bound actually requires.
`ORG_SWEEP_ROTATION_INDEX` is left unset in the job's `env:` block in
production so the sweep step computes it from wall-clock time; tests inject
it directly for determinism. That earlier version merged as `#1220` before
this correction landed (the review comment was informational, not a blocking
request-changes, so the org's merge scheduler proceeded once checks were
green) — this doc and the corrected workflow reflect the wall-clock version
as the durable design.

The budget-sizing question in #1219 (is `1` a deliberate LLM-provider
cost/rate ceiling, or an unconsidered default?) is explicitly **not**
resolved here. Raising the shared number without that context risks the
exact provider budget/rate-limit incident already documented in
`PR_GOVERNANCE_AUDIT.md` (2026-07-13 KST GitHub Models org budget cap
starvation). Rotation fixes starvation-by-fixed-order without touching that
open cost question; whoever has organization Billing/Budgets visibility can
still raise `vars.ORG_SWEEP_REVIEW_DISPATCH_LIMIT` independently later if the
ceiling turns out to be conservative.

## Consequences

- Every repository with ready work eventually reaches the front of the walk
  order and receives the shared dispatch, bounded by `repository_count`
  ticks in the worst case, instead of never.
- Total review dispatches per tick, and therefore LLM-provider call volume
  per tick, are unchanged.
- `rotation_offset` is logged (`Sweeping N repositories starting at rotation
  offset O (rotation tick T).`) so a specific tick's walk order is
  reconstructable from the run log alone.
- `ORG_SWEEP_ROTATION_INDEX` follows the same fail-closed numeric-validation
  pattern as the sibling `ORG_SWEEP_*_LIMIT` variables (reject non-digit
  input before it reaches arithmetic context, where an unguarded `set -e`
  would not trap the error), applied after the wall-clock default fills it in
  when the environment does not already provide one.

## Verification

- `tests/test_required_workflow_queue_contract.py::test_org_queue_sweep_rotation_offset_is_deterministic_and_reorders_targets`
  executes the extracted rotation snippet directly through `bash -euo
  pipefail` for several rotation indices and asserts the resulting order is a
  full permutation of the input, not a subset.
- `test_org_queue_sweep_rotation_offset_is_safe_with_no_targets` covers the
  zero-repository edge case.
- `test_org_queue_sweep_rotation_index_defaults_from_wall_clock` executes the
  extracted default/validation block standalone: confirms the unset case
  derives `$(date -u +%s) / 900` (within a one-tick boundary-race tolerance),
  an explicit override is preserved rather than overwritten, and a malformed
  override still fails closed.
- `test_org_queue_sweep_documents_rotation_leverage_and_validates_input`
  locks the `#1219` cross-reference, confirms `github.run_number` is not
  reintroduced as the source, and confirms the shared budget constant itself
  is untouched.
- `actionlint` (with `shellcheck` on `PATH`) reports no findings against the
  modified workflow.

## References

`ContextualWisdomLab/.github#1219` — original starvation report with sweep
run evidence.
`ContextualWisdomLab/.github#1220` — original rotation fix; review discussion
on the `run_number` vs. wall-clock rotation-tick source that this document
and the current workflow source reflect.
