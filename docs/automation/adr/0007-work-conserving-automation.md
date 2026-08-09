# ADR-0007: Work-conserving automation

Status: Accepted
Date: 2026-08-09
Owner: CWL automation maintainers

## Context

The organization automation runs periodically and manages many PRs,
repositories, operational debts, and product-control gaps. Checks, provider
reviews, eligible humans, queues, and rate limits often require external state
changes. Repeatedly polling one unchanged item consumes a run without improving
the repository and creates misleading progress. Stopping after a status report
also leaves other safe, independent work undone.

## Decision drivers

- Maximize substantive progress without competing writers.
- Respect CI, reviewer, provider, and ruleset authority boundaries.
- Avoid repeated reads, meaningless commits, and user-visible elapsed-time
  narration.
- Preserve exact deferred state and deterministic resumption.
- Permit product/documentation hardening when the PR queue cannot advance.

## Considered alternatives

1. Block the entire loop on the highest-priority PR. This wastes independent
   capacity and encourages polling.
2. Always create a commit to show activity. Meaningless mutations add risk and
   review noise.
3. Only report status and wait for the next schedule. Safe work remains idle.
4. Defer only the unchanged external dependency and continue another bounded
   safe lane under writer-lease rules. This is selected.

## Decision

A read, inventory, poll, wait, review request, dispatch, rerun, or CI start is
not substantive completion. After one fresh observation of an external wait,
record the exact repository/PR/head/dependency and next valid trigger. Do not
perform two consecutive reads of the same unchanged deferred item. Revisit it
only after external state changes, a substantive mutation/acceptance completes
in another lane, or a final sweep is due.

If a safe writable item exists, the run produces and exactly verifies at least
one substantive mutation. Candidate lanes include another PR/branch/repository,
a bounded buyer/operator control-plane gap, documentation/traceability debt, or
security/test hardening. The actor first checks writer ownership and branches
from the exact live protected tip. It never invents a low-value change merely
to satisfy the mutation rule.

## Consequences

Queue selection and handoff state become explicit. The loop makes progress
during local outages and approval waits. More than one item may be considered
per run, but source writes remain branch-scoped and reviewable. Runs with no
safe writable item can finish with a precise deferred record rather than fake
completion.

## Failure and recovery

If the selected mutation becomes unsafe or loses its lease, abandon it and
continue a different lane. If all lanes are externally blocked, persist owners,
exact identities, evidence, and next triggers, then stop cleanly. Provider/API
failures follow ADR-0003. Repeated failure across three distinct remedies
triggers architecture reassessment.

## Security and governance

Work conservation never bypasses independent review, checks, rulesets,
credentials, head guards, release gates, or protected-main acceptance. Parallel
work must not share a writer lease or mutate production. Read-only fleet audit
remains safe when mutation authority is unavailable.

## Verification

Prompt/queue contract tests or review verify one fresh read then defer, no
unchanged consecutive polling, progress on an independent lane, correct lease
behavior, no meaningless commit, exact handoff identity, and final sweep. Run
metrics count verified mutations/acceptances separately from observations.

## Migration and rollback

The hourly automation prompt was updated on 2026-08-09 with explicit anti-idle
and deferred-read caps plus a documentation-spine defect rule. Repository docs
make the contract durable. Rollback may simplify lane selection while retaining
one-read deferral and all authority gates; returning to indefinite polling is
not acceptable.

## Supersession

This ADR is current. A persisted queue/scheduler may supersede prompt-based
orchestration only if it preserves exact item identity, next-trigger semantics,
branch writer leases, work conservation, and the distinction between activity
and verified completion.
