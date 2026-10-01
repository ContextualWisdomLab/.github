# Authorized Draft review admission

## Incident

At `.github#2546@db81de7a09268eb0abfc5b5c675ddd9a0a38a3e2`, the explicit Draft-review
path had two individually valid halves that did not compose. The
agent-mention workflow wrote a one-day artifact named
`cwl-draft-review-request-<repository>-<pr>-<head-sha>`, and the merge scheduler
used that exact marker to authorize review-only dispatch. The central receiver
then required `live_draft=false` unconditionally before acquiring its lease.
The authorized request therefore could not reach semantic review.

This was a control-plane contract defect, not a reason to make the pull request
Ready or to weaken ordinary merge admission.

## Invariants

- The scheduler sends `draft_review_only` as a JSON boolean derived from live
  PR metadata; the receiver rejects any non-boolean envelope before external
  token exchange.
- Ready work is admitted only with `draft_review_only=false`.
- Draft work is admitted only with `draft_review_only=true` and a freshly
  fetched, exact repository/PR/head, non-expired central artifact.
- Artifact pagination or schema ambiguity, missing/expired markers, and any
  live state/base/head mismatch fail before Contents lease mutation.
- Every pre-mutation authority recheck also re-fetches the marker.
- A clean Draft emits an exact-head formal `COMMENTED` review with the explicit
  `DRAFT_REVIEW_COMPLETE` result; it never emits `APPROVED` authority.
- Only that exact-head result plus its review-only explanation satisfies the
  Draft scheduler, so stale and generic comments cannot suppress a new request.
- Draft review-only work does not create a merge receipt, publish Ready status,
  dispatch Noema, invoke the merge scheduler, or wake a merge-required OpenCode
  workflow.
- A Draft-to-Ready transition invalidates Draft authority before lease access;
  a validated Draft that changes later still publishes only a non-authorizing
  comment.
- The Ready-only Required producer always sends typed `draft_review_only=false`;
  omitted and malformed types fail closed at the receiver.
- Because the durable admission identity intentionally remains
  repository/PR/head/component, reconciliation retires an exact-head Draft
  completion lease when that pull request becomes Ready without an approving
  verdict. The same head can then acquire a fresh Ready review lease.

## Executable acceptance

The regression suite executes the extracted production shell. It proves that
an exact authorized Draft reaches lease validation, malformed/mismatched/
expired artifacts stop before lease access, ordinary Drafts remain rejected,
the dispatch payload distinguishes Ready and Draft work, and the Required
workflow wake is structurally disabled for a validated Draft. It also proves
that the Draft path cannot publish approval authority or start any Ready-only
follow-up, while its exact-head formal completion comment prevents an unbounded
same-head redispatch loop. A transition regression proves Draft completion,
same-head Ready retirement, and fresh Ready redispatch. The complete affected scheduler and receiver suite
must pass both locally and on the exact published head. Hosted security,
provenance, and independent semantic review remain required before ordinary
protected integration.
