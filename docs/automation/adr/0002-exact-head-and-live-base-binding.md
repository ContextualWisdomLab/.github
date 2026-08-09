# ADR-0002: Exact-head and live-base binding

Status: Accepted
Date: 2026-08-09
Owner: CWL automation maintainers

## Context

A pull-request object contains a source head and a base snapshot, but both refs
can change while review, testing, dispatch, or merge is in flight. Checks or
approvals for a predecessor head cannot justify a successor. Likewise, a stale
base snapshot cannot answer whether the current protected branch makes the PR
behind, conflicting, or unsafe to merge. Cross-repository dispatch adds another
point where identity can be truncated, malformed, or replayed.

## Decision drivers

- Prevent time-of-check/time-of-use and predecessor-evidence reuse.
- Distinguish source revision from target branch freshness.
- Preserve enough identity for audit, retry, handoff, and incident response.
- Fit GitHub's dispatch payload and final merge transaction constraints.
- Fail closed on ambiguity without serializing unrelated work.

## Considered alternatives

1. Trust the PR API's embedded base SHA throughout a run. It is historical and
   can differ from the live protected ref.
2. Bind only to PR number and branch names. Branches are mutable and therefore
   insufficient evidence identity.
3. Bind only to source SHA. This misses base movement and dependency freshness.
4. Seal source and independently observed live-base identity at every decision
   boundary, with a final expected-head guard. This is selected.

## Decision

The canonical snapshot tuple is `(repository, pr_number, source_ref,
source_head_sha, base_branch, live_base_sha, observed_at)`. Evidence additionally
records producer, type, workflow provenance, run/job, and conclusion.

The source head comes from the live PR/ref and is immutable for that evidence.
The live base is resolved independently from the current base branch at the
decision boundary; the PR's base SHA is retained only as historical context.
Source movement invalidates predecessor tests, statuses, checks, reviews,
patches, and merge simulations. Base movement forces a new freshness,
mergeability, and dependency decision. Writes use expected-head semantics and
merges use a head-matched transaction.

The three-key `cwl.agent-invocation/v2` envelope and snapshot-only route in
`ContextualWisdomLab/.github#840` are pending, not protected-main behavior.

## Consequences

Runs refetch more often and some expensive evidence becomes stale by design.
Operators can explain exactly why evidence was accepted or rejected. Dispatch
schemas stay bounded and versioned. A check on the same commit may still need
rerun after a meaningful base movement because integration assumptions changed.

## Failure and recovery

Malformed repository/ref/SHA, missing live base, unexpected head, or schema
version failure is permanent for that attempt and fails closed. API 5xx or
bounded network reset may retry under ADR-0003. On movement, abandon the old
mutation, record the new identity, and enqueue a fresh snapshot; do not edit
evidence labels to make old results appear current.

## Security and governance

All identity fields are validated as untrusted inputs. Protected workflow code
re-fetches rather than trusting dispatcher assertions. Exact-head binding does
not make the producer authoritative: formal review eligibility, rulesets,
permissions, and separate merge/release authority still apply.

## Verification

Tests cover force-push, deleted/ref-created branch, stale PR base snapshot, live
base movement, cross-repository head, malformed SHA/ref, replayed dispatch,
payload property limits, predecessor review/check, and movement immediately
before update or merge. Verification asserts the final expected-head value.

## Migration and rollback

Consumers first accept both legacy and versioned dispatch formats while
producers emit the strict format; receipts expose which schema was used. Remove
legacy acceptance only after protected-main consumer evidence. Rollback keeps
exact-head/live-base validation while reverting the envelope producer/consumer
pair; weakening identity is not an allowed rollback.

## Supersession

This ADR is current. A successor may change transport or snapshot storage, but
must preserve independent source/live-base observations, typed provenance, and
final atomic head protection.
