# CodeQL dispatch multi-language wake race

## Incident evidence

On 2026-09-09, `.github` PR #1857 at
`afeffe3b6a7a5494be1dae12322a0fc2a78c6efe` dispatched run `34320386978`
after both initial CodeQL required jobs reported pending. Its `actions` scan
completed successfully, but the subsequent Python wake failed with GitHub's
`The workflow run containing this job is already running` HTTP 403. The first
per-language rerun had already reactivated the shared required-workflow run.

The scan itself was not the failing evidence: both the CodeQL analysis and the
Medium-or-higher SARIF gate completed. A status publication 403 is separately
recorded as non-terminal for a clean scan, as required by the existing status
publication contract.

## Corrective action

`codeql-scan-dispatch.yml` now waits for the complete matrix and uses one
run-level `rerun-failed-jobs` call. Before that mutation, it revalidates the
open PR and exact head, validates the required workflow run identity, fetches
all jobs, and refuses unless the full failed-job identifier set exactly equals
the authenticated CodeQL binding. This preserves the no-unrelated-job
invariant without relying on concurrent per-job reruns.

## Verification and recovery

`tests/test_codeql_scan_dispatch_workflow_contract.py` executes the wake
block against fixture-backed GitHub responses. It covers the bounded job set,
stale and closed pull requests, a mismatched or nonfailed job set, and an
already-running required workflow. Hosted exact-head evidence remains required
before any PR or consumer result is treated as successful. If the binding does
not match, do not retry a job manually; inspect the exact run and dispatch a
new current-head scan only through the owner workflow.

### Bootstrap boundary

On 2026-09-09, PR `#2056` at
`aad55ed864db3466d52d24dcd88a80d15e84996d` triggered dispatch run
`34322210652` for required run `34321725703`. The run executed the protected
default-branch handler, as GitHub defines for `repository_dispatch`; its log
therefore used the old per-job wake and reproduced the same HTTP 403 when the
second shard tried to rerun an already-running required workflow. This does
not execute or disprove #2056's proposed run-level wake.

The branch cannot use `workflow_dispatch` as a substitute: that would let a
caller select an unprotected workflow ref while minting privileged cross-repo
credentials, and the central queue contract forbids it. The pre-merge proof is
the fixture-backed contract plus actionlint. After protected integration, a
fresh default-branch dispatch must prove the one-call wake against an exact
current head before a consumer adopts the owner.
