# Contextual Orchestrator Noema control allocation

## Structure and gap

After #2420, the four metadata-only Noema jobs used the control group only for
`.github`. Contextual Orchestrator still placed admission and scope detection
in the two-runner model pool. On 2026-09-27, run 36314265013 had both jobs queued
with no runner assignment while both remediation runners were busy. All five
organization runners were online; the idle CodeQL runner was workflow-restricted.

## Allocation

Apply the existing control allocation to both already admitted repositories.
Keep the trusted-main guard, hosted fallback, exact-head admission, permissions,
and model job unchanged. The control group permits all repositories but limits
execution to explicit central workflows at main; its allowlist already includes
Noema. These four jobs do not check out PR code. No optimizer or broader runner
access is needed for this fixed eligibility partition.

## Verification and limits

The five focused runner, queue, admission and Noema contract files completed
222 tests locally. Actionlint passed. Hosted current-head execution and actual
queue drainage must be checked after deployment; local tests do not establish
runner capacity or independent model approval. Rollback restores only the four
runner expressions from parent revision efe71f4.
