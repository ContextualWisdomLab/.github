# Closed and superseded CodeQL compatibility shards

## Incident and root cause

ContextualWisdomLab/fast-mlsirm#2172 merged at 2026-09-26 11:05:49 UTC.
The actions compatibility shard in [run 36237658142](https://github.com/ContextualWisdomLab/fast-mlsirm/actions/runs/36237658142/job/108414341704)
started its live PR read at 19:47 UTC. It correctly observed the closed PR and
returned without requesting a scan. The next step saw a successful read with
an empty verdict and failed with `CodeQL shard has no authenticated current-head
verdict or dispatch receipt.` The same producer/consumer mismatch existed when
the live open PR head differed from the event head.

The queue delay exposed this bug; delay itself does not explain the failed
verdict contract. The missing output is the causal defect.

## Repair and boundaries

The live read now emits `verdict=obsolete` for a closed PR or a live head proven to descend from the event head.
Enforcement accepts that state without asserting a successful scan and without
publishing a security status. A lagging or diverged head, failed/incomplete comparison, malformed SHA, or unknown PR state fails
before retirement. Open PRs at the event head still require the existing
trusted terminal verdict; pending, failed, missing and unauthenticated evidence
remain failures. No permissions, security severity or required gates change.

This repairs the required workflow compatibility layer. It does not replace
#2382's separate dispatch-handler stale-run repair or change an already-recorded
historical check result.

## Verification

Tests execute the actual workflow shell blocks with a stubbed GitHub API.
Closed and superseded targets reproduce the missing-output failure on the
baseline and pass with the repair. Unknown states, malformed SHAs and unproven forward ancestry fail in
both the read and enforcement steps. Existing exact-head verdict tests cover
trusted failure, spoofed success, missing evidence and terminal dispatch receipts.

## Primary platform basis

GitHub. (n.d.). *Workflow commands for GitHub Actions: Setting an output parameter*.
https://docs.github.com/en/actions/reference/workflow-commands-for-github-actions#setting-an-output-parameter

GitHub. (n.d.). *Contexts reference: Steps context*.
https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#steps-context

## Existing security baseline repaired with the consumer

The repository's open Dependabot alerts 11–13 identify AnyIO 4.14.0 in
`requirements-strix-ci-hashes.txt`. The Critical and High advisories are
GHSA-82r6-8w77-94w6 and GHSA-3w57-8xmc-8v26; the patched version is 4.14.2.
The source pin, two release hashes and source/lock parity test are reused from
#2385 at `372f5b8bb1ae1bb32ab29e9afbe363d81aed81e3`, without claiming that PR's
other changes or checks have been inherited. Both release digests were verified
against PyPI's version-specific JSON. This removes the known vulnerable lock
entry while preserving the repository-wide security gate.

GitHub. (2026). *AnyIO: TLSStream IDNA 2003 host name encoding enables potential
TLS certificate spoofing* (GHSA-82r6-8w77-94w6).
https://github.com/advisories/GHSA-82r6-8w77-94w6

Python Package Index. (2026). *AnyIO 4.14.2*.
https://pypi.org/project/anyio/4.14.2/
