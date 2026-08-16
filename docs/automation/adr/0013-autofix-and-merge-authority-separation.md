# ADR-0013: Separate autofix authority from merge authority

Status: Accepted
Date: 2026-08-09
Decision owners: CWL governance maintainers

## Context

Autofix may modify an eligible same-repository PR head, while the merge
scheduler may integrate a policy-clean exact head. Combining them lets a repair
actor approve or merge its own unreviewed output and makes credential scope and
incident attribution ambiguous.

## Decision drivers

- Every generated change receives fresh independent evidence.
- Least-privilege, purpose-specific mutation credentials.
- Expected-head race protection and branch-local writer exclusion.
- Clear recovery when conflict or validation fails.

## Alternatives considered

1. **One omnipotent repair-and-merge workflow.** Rejected due self-authorization
   and blast radius.
2. **Disable all automated repair.** Rejected because bounded source-actionable
   fixes can safely reduce maintenance toil.
3. **Distinct fix and merge paths with a mandatory new-head gate cycle.**
   Selected.

## Decision

The autofix scheduler may dispatch the trusted autofix worker only for an
allowlisted, source-actionable, current-head finding on a mutable
same-repository branch. It acquires a branch writer lease, checks expected head
before checkout and push, produces the minimum diff, runs focused gates, and
publishes a new commit without approval or merge authority.

The merge scheduler cannot reuse predecessor-head evidence. It re-fetches the
new head and requires all deterministic, security, formal-review, thread,
ruleset, mergeability, and last-pusher conditions before an expected-head merge.
Model exhaustion, process blockers, failed peer checks, external heads, and
unresolved conflicts are not autofix invitations.

## Consequences

Generated changes cannot bypass review, and failures have an identifiable
owner. Repair-to-merge latency increases because the complete gate cycle runs
again.

## Failure and recovery

If the head moves, validation fails, the diff exceeds scope, or the lease is
lost, the worker publishes no push. Conflict repair remains on the PR branch
and must still pass a new-head cycle. A merge failure triggers a live evidence
refresh, never an autofix retry by implication.

## Security and governance impact

Fix credentials write only eligible PR branches; merge credentials invoke only
the guarded GitHub merge primitive. Neither path can publish a qualifying human
review. Logs and receipts name the actor class without exposing tokens.

## Tests and acceptance

- eligibility and non-actionable-blocker tests;
- expected-head checks before checkout, commit, push, and merge;
- writer-lease contention tests;
- generated-head invalidation of all predecessor evidence;
- credential/actor separation assertions; and
- protected-main proof that a real generated head was independently rechecked
  and reviewed before merge.

## Migration and rollback

Remove merge permissions from autofix jobs, remove repair permissions from the
merge path, add the new-head gate assertion, then canary one safe repository.
Rollback disables autofix dispatch while leaving manual repair and the guarded
merge scheduler available.

## Supersession conditions

Supersede only if GitHub supplies a native proposed-change object that is
cryptographically bound to mandatory independent review and cannot be merged by
its proposing authority.
