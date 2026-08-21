# ADR-0015: Guarded `direct_or_auto` merge state machine

Status: Accepted
Date: 2026-08-09
Decision owners: CWL governance maintainers

## Context

Repositories differ in native auto-merge availability and immediate merge
policy. A scheduler must not leave an approved clean PR idle when direct merge
is allowed, nor bypass policy when direct merge fails. Historical documentation
described only `auto`, `direct`, and `disabled`, while the implementation uses
`direct_or_auto` as the default compatibility mode.

## Decision drivers

- One explicit, race-safe merge policy per scheduler run.
- Productive fallback without converting policy/integrity errors into success.
- External heads and non-clean states remain outside automated merge.
- Every merge is bound to the expected current head.

## Alternatives considered

1. **Auto-merge only.** Rejected because repositories without native support
   remain idle.
2. **Direct merge only.** Rejected because queueing native policy is sometimes
   the correct integration path.
3. **Ordered `direct_or_auto` with classified fallback.** Selected.

## Decision

The supported modes are `disabled`, `auto`, `direct`, and `direct_or_auto`.
`direct_or_auto` first attempts a guarded expected-head direct merge only for a
clean, same-repository, policy-authorized head. It falls back to native
auto-merge only for an explicitly classified “direct unavailable but auto
eligible” response. Head movement, failed/absent evidence, unresolved threads,
external heads, conflicts, authorization, and integrity errors do not fallback.

One run performs these steps serially under the branch writer contract. It
re-fetches live state around each mutation. A queued auto-merge is a wait state,
not integration or operational acceptance.

## Consequences

Eligible PRs progress across heterogeneous repository settings with a concrete
logged outcome. Error classification and tests are more complex, and the mode
must remain visible in result receipts.

## Failure and recovery

A rejected direct attempt records the exact class. Eligible compatibility
failure may queue auto-merge; every other failure stops mutation and returns to
live inspection. Recovery occurs on a new event/sweep with fresh evidence.

## Security and governance impact

Neither path weakens rulesets, approval counts, last-pusher separation, thread
resolution, current-head checks, or expected-head semantics. External/fork
heads require a maintainer merge after evidence remains current.

## Tests and acceptance

- each mode and unsupported value;
- direct success and the narrow eligible fallback;
- head movement, external head, conflict, policy, authorization, and failed-gate
  negative paths;
- no simultaneous direct/auto writer; and
- scheduler v2 receipt plus protected merge/queued-state evidence.

## Migration and rollback

Expose the mode in workflow inputs and result schema, canary
`direct_or_auto`, then use it as the default. Rollback selects `auto`, `direct`,
or `disabled` explicitly without changing evidence gates.

## Supersession conditions

Supersede if GitHub offers one universal expected-head merge primitive with
native queuing, classified errors, and equivalent ruleset enforcement.
