# ADR-0007 — Require counted independent exact-head review

Status: active_pr

## Context

Automated comments, statuses and model verdicts are useful evidence but are not GitHub-counted independent human approval. Reviews can also become stale when the head moves.

## Drivers

Preserve real governance, reviewer identity, head binding and branch protection without idling other lanes.

## Alternatives

1. Count any positive text. 2. Allow author or alternate credentials. 3. Require a qualifying non-author formal approval that applies to the exact head.

## Decision

Choose option 3. Advisory automation remains separate. When approval is the sole gate, expected-head-safe auto-merge may remain enabled while other work continues.

## Consequences

Some integrations wait for human capacity; the repository never manufactures governance evidence.

## Failure and recovery

A moved head invalidates prior acceptance according to repository policy. Dismissed, commented, reaction, status and predecessor evidence are ignored.

## Security and governance impact

Prevents reviewer spoofing, self-approval and protection bypass. Reviewer eligibility is evaluated from GitHub identity and current policy.

## Tests and acceptance

Tests cover author, bot, dismissed, stale-head and status-only cases plus one qualifying reviewer. Merge evidence must bind the expected head.

## Migration and rollback

Adopt in the scheduler and documentation before removing legacy positive-text paths. Roll back by disabling merge automation, never by weakening protection.

## Supersession conditions

Supersede only if organization policy provides a stronger independently auditable approval mechanism.
