# Aggregate review approval is a merge gate

## Incident

The scheduler treated a current-head OpenCode `APPROVED` review as sufficient
to enable or retain native auto-merge. That was unsafe when GitHub's aggregate
`reviewDecision` remained `REVIEW_REQUIRED` (or another non-approval state),
which is the state that represents missing code-owner, independent, or other
branch-protection review policy.

The defect was observed while auditing the exact current heads of
`ContextualWisdomLab/.github#965`,
`ContextualWisdomLab/contextual-orchestrator#109`, and
`ContextualWisdomLab/fast-mlsirm#816`: the scheduler could re-enable
auto-merge after seeing the automated current-head review even though GitHub
reported `REVIEW_REQUIRED`.

## Decision

The scheduler now requires both signals before it can merge or enable
auto-merge:

1. OpenCode approved the exact current head.
2. GitHub's aggregate `reviewDecision` is exactly `APPROVED`.

Missing, empty, `REVIEW_REQUIRED`, and `CHANGES_REQUESTED` aggregate states
fail closed. An existing auto-merge request is disabled; otherwise the PR is
blocked. The REST fallback continues to use `REVIEW_REQUIRED` because it does
not expose the GraphQL aggregate decision, so REST-only data cannot create
merge authority.

This is a merge-policy gate, not a replacement for terminal current-head
checks, structured Strix evidence, resolved review threads, independent
approval, or protected-branch enforcement.

## Verification

`tests/test_pr_review_merge_scheduler.py` covers every non-approval aggregate
state and asserts that neither merge nor auto-merge is invoked. The focused
scheduler suite passes with 114 tests.
