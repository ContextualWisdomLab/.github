# ADR-0001: Branch-local writer leases and a separate read-only fleet audit

Status: Accepted
Date: 2026-08-09
Decision owners: CWL repository maintainers

## Context

Multiple agents, scheduled maintainers, Jules, dependency bots, and humans may inspect or change the same repository. Treating any activity as a repository-wide lock wastes capacity; ignoring writers risks lost work, invalid tests, wrong-thread resolution, and non-fast-forward or destructive recovery.

## Decision drivers

- Preserve every actor's work and source history.
- Allow non-conflicting branches and read-only audits to proceed concurrently.
- Bind a write to the exact branch head inspected immediately beforehand.
- Make collision recovery observable and non-destructive.
- Avoid private-memory-only ownership claims.

## Alternatives considered

1. **No lease; rely on Git conflicts.** Rejected because API writes, comments, thread resolution, and branch mutations can race without a file conflict.
2. **One repository-wide writer lock.** Rejected because a waiting PR would idle unrelated branches, docs, issues, and operations.
3. **Branch-local writer lease plus independent read-only audit.** Selected because it limits exclusivity to the mutable target while preserving fleet visibility and throughput.

## Decision

Every source/ref/PR-state writer owns one repository/ref/expected-head tuple for a bounded interval. Immediately before mutation it re-fetches the target head/base and relevant writer state. If source-affecting state moved or another write-capable actor owns the branch, it stops writing that branch and rotates to disjoint work.

Read-only fleet auditors may inspect all repositories and produce evidence/handoffs but never mutate source, refs, PR state, reviews, or Project status. Review/check execution alone is not a source-writer conflict.

## Consequences

Positive: collisions are localized, unrelated work continues, and stale local state cannot authorize a write. Negative: the lease is partly procedural until a durable shared ledger exists; last-moment API refreshes add latency and complexity.

## Failure and recovery

On movement or collision, preserve both trees, capture exact remote/local heads, stop writes, and prepare a manual or separately reviewed reconciliation. Never force-push, wholesale-select `ours/theirs`, reset another actor's work, or deploy a one-shot repair workflow. If the lease holder disappears, expire the lease only after live branch and actor evidence shows no active writer.

## Security and governance impact

The lease narrows mutation authority and reduces confused-deputy and TOCTOU risk. It does not grant review or merge approval and cannot override branch protection.

## Tests and acceptance

- moved-head/base and duplicate-dispatch tests;
- expected-head branch update/merge/autofix rejection;
- mention idempotency and exact artifact-ledger tests;
- a live collision exercise showing no source loss; and
- queue rotation while the blocked branch remains untouched.

## Migration and rollback

Document writer identity and expected head in Project/issue/automation state where supported. Existing branch writers adopt the last-moment refresh before mutation. Rollback removes only the shared ledger implementation; expected-head and non-destructive behavior remain mandatory.

## Supersession conditions

Supersede when GitHub provides an authoritative native branch-write lease with identity, expiry, and expected-head enforcement, or when a reviewed central lease service provides stronger guarantees without becoming a single availability bottleneck.
