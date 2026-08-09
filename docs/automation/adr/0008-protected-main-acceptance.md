# ADR-0008 — Require protected-main operational acceptance

Status: active_pr

## Context

A source PR can pass static and exact-head tests while a scheduled, manual, OIDC, dispatch, concurrency or downstream-consumer boundary still fails after merge.

## Drivers

Close operational incidents on real behavior, retain negative controls, and prove rollback.

## Alternatives

1. Close on PR checks. 2. Close on merge. 3. Require a protected-main consumer run through the repaired boundary.

## Decision

Choose option 3 for operational defects. Acceptance records the protected revision, event, consumer, acknowledgement, negative control and rollback rehearsal.

## Consequences

Incident closure takes longer but reflects deployed control-plane behavior rather than source intent.

## Failure and recovery

If the consumer does not exercise the boundary or evidence is stale, the incident remains open. Roll back the narrow integration on regression.

## Security and governance impact

Prevents false closure, stale evidence transfer and untested credential/dispatch behavior.

## Tests and acceptance

Require real scheduled/manual receipt, downstream acknowledgement, zero secret disclosure, failure-mode negative control, and observable rollback.

## Migration and rollback

Add acceptance criteria before merge and run the consumer immediately after integration. Revert the protected commit or disable the caller if acceptance fails.

## Supersession conditions

Supersede only with deployment verification that provides at least the same protected-runtime evidence.
