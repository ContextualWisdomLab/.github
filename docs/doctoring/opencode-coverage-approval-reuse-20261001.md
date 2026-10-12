# OpenCode coverage approval-reuse gate

**Status:** Proposed on `ContextualWisdomLab/.github#2536`; fresh exact-head
hosted Checks and qualifying independent approval remain mandatory.

## Failure evidence and root cause

CodeRabbit review thread `PRRT_kwDOS_C14s6nmf3Q` identified a fail-open edge in
the current PR head: `publish_blockers_after_model_unavailable` and
`scripts/ci/opencode_dispatch_status.py` required only the coverage job result
`success` before reusing an existing same-head OpenCode approval. A later audit
also found the merge-scheduler's direct approval-gate invocation omitted the
coverage summary. The coverage
producer intentionally completes successfully for an honest `NOT MEASURED`
result so that it can publish diagnostics without fabricating a source defect.
Consequently, job success alone is not proof that the current dispatch measured
and passed coverage.

The causal owner is the central `.github` OpenCode review boundary, not a
consumer repository or the model provider. The defect was an incomplete
evidence contract between the coverage producer and the approval/status
consumers.

## Test-first repair

The RED regression added missing, `NOT MEASURED`, malformed, and duplicate
coverage-decision cases and failed because no decision validator existed. The
repair introduces one shared Python validator that accepts exactly one
`- Result: PASS` line, applies it before existing-approval reuse and status
publication, and mirrors the same exact rule in the workflow shell path. The
workflow now supplies the current coverage summary to both consumers.

The focused approval, security-boundary, workflow-contract, executable shell,
and reviewed-blob suites pass 186 tests with 1 optional LLVM-platform skip.
This includes concurrent exact-head commits
`87ffafa2f6b19080c01f6ee24b987b37cb92dcb8`,
`0bcded6b08af4554541223438d046bc412c4b093`, and
`feb88e34c9197275a58310306492069e25eb0b67`; their additional environment,
prefixed-result, contradictory-result, implementation, and coverage cases were
preserved rather than overwritten. After integration, the
warnings-as-errors repository suite passes 5,255 tests, 5 optional skips, and 40
subtests. No timeout, coverage threshold, exact-head rule, independent-review
rule, or required Check is relaxed. Missing or ambiguous evidence remains a
failure, while an honest unmeasured result remains diagnostic rather than being
relabeled as a code finding.

Fresh exact-head Trusted uv run
[`36751696675`](https://github.com/ContextualWisdomLab/.github/actions/runs/36751696675),
job `110011676248`, then exposed a test-contract omission: the suite passed, but
`scripts/ci/opencode_existing_approval_gate.py:241-242` remained unexecuted, so
the repository coverage gate reported 18,252 statements with 2 misses and
7,498 branches with 1 partial branch (99%). The repair executes the real CLI
with `NOT MEASURED` and asserts its fail-closed diagnostic. It does not exclude
the branch or lower the 100% threshold. The exact hosted command reproduced
locally with 5,255 passed, 5 optional skips, and 40 subtests, covering all
18,252 production statements and 7,498 branches at 100% with zero misses or
partial branches.

## Operational consequence

Existing approvals remain reusable only when all of the following are true:

1. the approval is valid for the exact live head;
2. the coverage evidence job completed successfully; and
3. its current summary contains exactly one authoritative `PASS` decision; and
4. every approval consumer, including merge scheduling, receives that summary.

Fresh hosted execution on the repaired head is still required. Predecessor
GREEN, skipped CodeQL, pending dispatch verdicts, or this local result do not
authorize merge.
