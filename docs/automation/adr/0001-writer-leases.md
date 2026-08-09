# ADR-0001 — Dedicated repository writer leases and read-only fleet audit

Status: Proposed

## Context

Concurrent autonomous writers can invalidate exact-head evidence, overwrite unrelated work, and create self-amplifying repair loops.

## Alternatives

1. Allow all loops to write everywhere.
2. Use a single organization-wide writer.
3. Assign one authoritative writer per repository and keep fleet audit read-only.

## Decision

Use option 3. Enabled dedicated loops own writes to their repository. General fleet development skips those repositories. Fleet incident auditing remains read-only. Conflicts are branch-local when evidence supports that scope.

## Consequences

This reduces races and preserves modular repository ownership, at the cost of explicit handoffs for central dependencies.

## Failure and recovery

If another writer moves the target ref/blob/head between required reads, discard stale assumptions, freeze writes to that branch for the invocation, and rotate. Reacquire from fresh evidence later.

## Security and governance

Never bypass the lease using one-shot workflows, force-push, alternate credentials, or a second autonomous writer.

## Acceptance

Tests and automation contracts must demonstrate lease derivation, stale-write refusal, and read-only fleet audit behavior.

## Supersession

Supersede only if a stronger transaction/lease mechanism provides equivalent or better race prevention across all supported write paths.