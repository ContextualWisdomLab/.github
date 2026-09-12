# CodeQL versioned handler bootstrap — 2026-09-12

## Status

Proposed repair from protected `main@691fb78932eff5fbe52db69077848134b0b4e053`.
No merge or production claim is made here. The complete consumer successor is
PR #2040, revalidated at current head
`6476b919d3febf79cc53e71d6d60f15d7e83ced4`.

## Exact live evidence

PR #2040 predecessor head `a9b18b4b24980c7ceb8b8cc0d143a24db20c90bf`
had successful Runtime Quality run `34684155351` (3,127 passed, 1 skipped,
21 subtests; 100% statement, branch, and public-doc coverage), Security run
`34684356405`, SAST run `34684356377`, and Python Security run `34684356416`.
It had no unresolved review threads. The later current head `6476b919...`
moves replay-guard tests without changing this handler source, but historical
hosted results are not inherited. The current head is Draft and had no
associated pull-request workflow runs in the connector snapshot. It therefore
remains unmergeable through ordinary protection.

Protected handler run `34684228601` is the smallest causal trace. Its Actions
and Python scan, SARIF gate, artifact preservation, and status paths reached
terminal completion. The Actions shard then woke the shared required run. The
Python shard's independent wake received HTTP 403 because that run was no
longer in the terminal-failed state. Same-repository/PR handler runs
`34684373526`, `34684458709`, `34684518320`, and `34684575249` were then
cancelled by the stable concurrency group while retries kept dispatching. In
`34684575249`, Python produced clean scan evidence while its sibling and wake
path did not converge. The repeated consumer symptom was a dispatched success
with a pending terminal verdict.

## Root cause

The protected handler woke the required run independently from each matrix
scan job. The first wake changed the run state before the second language
could validate and mutate it. In addition, a candidate stronger consumer
could not prove itself against protected `main`: the old handler lacked its
source-bound title and base-bound receipt, while replacing the handler in one
step would reject the still-protected legacy producer. Re-running either side
alone reproduces the dependency cycle.

## Repair contract

One existing handler accepts `codeql-scan` legacy v1 and `codeql-scan-v2`.
The event type is the explicit protocol version, avoiding an eleventh
top-level `client_payload` property. v1 retains the current title, payload,
and status context byte-for-byte at the boundary, while rejecting all v2-only
identity fields. v2 requires the exact source/base/head evidence implemented
by #2040. Both use the same scan implementation and one post-matrix settlement
writer. No scan shard has `actions:write`.

The bridge removal condition is executable policy: remove v1 only after a
protected v2 producer is live, every in-flight v1 required run is terminal,
and a caller inventory finds zero `codeql-scan` producers. Until then, v1 is a
bounded compatibility port, not production authority for v2 consumers.

## Verification and next action

The bootstrap contract executes both payload shapes, rejects v2-to-v1
downgrade fields, verifies one actions writer after the matrix, and preserves
the legacy and base-bound contexts separately. The full repository suite and
hosted exact-head checks must pass before ordinary merge. After bootstrap
merge, #2040 must non-force absorb protected main, change only its producer
event to `codeql-scan-v2`, and generate new end-to-end evidence; existing
failed or queued runs are not inherited.

PR #2106 review then exposed a credential-fallback contamination edge case:
`gh api` may emit an HTTP error body to stdout before returning nonzero, so a
failed credential's JSON could precede the later credential's successful
response. A generic `{"message":"Forbidden"}` body was already discarded by
the current `jq` projections and therefore was not RED. The corrected RED
fixture emits `{"state":"closed"}`, a field the PR validator consumes: before
the repair it is concatenated with the authorized response and rejects that
valid fallback. `run_api` now captures each attempt and emits its body only
after that exact attempt succeeds, preserving stderr diagnostics and the
existing credential order without a temporary-file lifecycle.
