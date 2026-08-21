# ADR-0016: Fail-closed composition of independent security and review gates

Status: Accepted
Date: 2026-08-09
Decision owners: CWL security and governance maintainers

## Context

The control plane receives checks, commit statuses, formal reviews, model
outputs, scanner findings, threads, ruleset parameters, and workflow receipts.
Treating any one signal as aggregate approval, or treating skipped/pending tool
execution as success, allows coverage gaps and confused authority.

## Decision drivers

- Independent detection layers retain their issuer and meaning.
- Required absence, skip, cancellation, staleness, or ambiguity is non-passing.
- Provider/tool failure is distinguished from a source finding.
- Live repository policy remains the final configured gate inventory.

## Alternatives considered

1. **One aggregate bot status.** Rejected because it hides missing and stale
   authorities.
2. **Fail open on unavailable model/scanner.** Rejected because tool outage can
   authorize unreviewed code.
3. **Intersect live required authorities and fail closed per configured gate.**
   Selected.

## Decision

Merge eligibility is the intersection of live ruleset/branch policy, exact-head
deterministic checks, configured security gates, qualifying formal approvals,
last-pusher separation, current thread state, mergeability, expected-head
identity, and writer authority. Check, Status, Review, model, scanner, workflow,
and operational evidence remain distinct records.

A required gate that is absent, pending, queued, skipped, neutral, cancelled,
timed out, stale, malformed, or unavailable is non-passing. An optional advisory
route may be skipped only when policy explicitly labels it optional; that skip
cannot satisfy another required class. Tool failures produce operational
diagnosis, not invented source findings or approval.

## Consequences

Coverage gaps are visible and cannot silently authorize merge. Provider outages
can delay affected PRs, so work-conserving rotation, bounded retries, and clear
operator receipts are required.

## Failure and recovery

Classify the failing authority, preserve its exact receipt, and retry only
eligible transient failures. Restore the gate or land a separately reviewed
policy change; never edit a result to success. Any new head reruns the entire
applicable intersection.

## Security and governance impact

The model resists status/review impersonation, stale evidence reuse,
fail-open outages, and scanner suppression. Ruleset changes require live audit,
independent review, rollback, and consumer proof.

## Tests and acceptance

- every evidence class remains non-interchangeable;
- absent/pending/skipped/neutral/cancelled/stale/malformed negative fixtures;
- provider failure cannot synthesize approval or a source finding;
- live ruleset inventory and two-approval/last-pusher/thread assertions; and
- protected-main canary demonstrating all configured authorities and one
  negative control.

## Migration and rollback

Inventory current gates and issuer identities, separate aggregate signals,
enable fail-closed behavior with diagnostic summaries, then require it in the
ruleset. Rollback reverts a broken implementation while retaining the previous
reviewed gate inventory; it does not disable gates ad hoc.

## Supersession conditions

Supersede when a policy engine can cryptographically attest the same independent
authorities, exact revision, live policy version, and fail-closed semantics.
