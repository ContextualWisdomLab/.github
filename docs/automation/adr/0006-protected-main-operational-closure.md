# ADR-0006: Protected-main operational closure

Status: Accepted
Date: 2026-08-09
Owner: CWL automation and operations maintainers

## Context

Central workflows can pass unit and integration tests on a PR head yet fail
after merge because required-workflow resolution, repository context, rulesets,
permissions, Apps, secrets, event delivery, or a leaf repository differ from
fixtures. Calling an incident resolved when source merges hides this deployment
boundary and has repeatedly encouraged premature closure.

## Decision drivers

- Prove the exact protected implementation works in its real execution context.
- Keep source correctness separate from deployment and operational acceptance.
- Preserve target/run/revision identity for audit and rollback.
- Limit blast radius through staged representative consumers.
- Define an unambiguous reopen condition.

## Considered alternatives

1. Close at PR merge. This proves integration only.
2. Use a central synthetic workflow run. This misses target-repository rules,
   secrets, permissions, and event context.
3. Wait for passive fleet usage with no explicit receipt. This is slow and
   difficult to attribute.
4. Require a staged real-consumer execution from protected main and retain its
   identity before operational closure. This is selected.

## Decision

For an operational defect in central automation, source merge moves the
incident to deployed/monitoring, not resolved. Closure requires at least one
enrolled real consumer to execute the changed protected-main path with recorded
central workflow revision, target repository, event, source head, current live
base, run/job/attempt, conclusion, relevant evidence objects, and expected
failure/recovery behavior.

The consumer is representative of the changed boundary: for example, a
cross-repository dispatch change needs a target repository dispatch and receipt;
a redaction change needs real subprocess output through the publication path;
a merge-scheduler change needs a ruleset-governed target state. High-blast-radius
changes expand the canary set before fleet-wide closure.

## Consequences

Incidents remain open longer than their PRs, and operational acceptance becomes
a first-class artifact. Some changes need a non-destructive probe or prepared
fixture in a real repository. False confidence falls, but operators must own
consumer selection and evidence retention.

## Failure and recovery

If the protected-main consumer fails, preserve the exact receipt, contain the
affected path, and choose a reviewed corrective change or revert from the
current protected tip. Do not retry permanent authority/integrity failures or
call a different synthetic path equivalent. After recovery, repeat the same
boundary and verify rollback behavior when applicable.

## Security and governance

Consumer probes are least privilege, non-destructive where possible, and do not
weaken rulesets. Secrets stay scoped to the real action boundary. Operational
acceptance cannot substitute for formal review or source gates; it follows
them. Evidence audience and retention follow the security contract.

## Verification

Pre-merge tests simulate event/context and negative paths. Post-merge evidence
must link a successful real run/job and target revision and demonstrate the
changed code path, not merely an unrelated workflow success. Failure-path fixes
also show the expected diagnostic and recovery signal.

## Migration and rollback

Add acceptance fields to incident/handoff records and start with highest-impact
central workflow changes. Existing resolved incidents are not retroactively
rewritten but can be sampled for gaps. Rollback is a normal reviewed revert or
known-good explicit pin followed by the same real-consumer verification.

## Supersession

This ADR is current. A future automated promotion system may collect acceptance
receipts, but must retain real-consumer context, exact provenance, staged blast
radius, failure/reopen behavior, and an auditable owner.
