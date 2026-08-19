# ADR-0012: Govern adaptive orchestration defaults centrally

- Status: Accepted
- Date: 2026-08-19

## Context

Consumers can silently bypass contextual-orchestrator by forcing a fixed
`route` mode or by omitting the mode from a chat request. That makes the
quality-before-cost policy in the consumer contract unenforceable by review
alone.

## Decision

The central repository ships a small source scanner and a reusable workflow.
Production source that names contextual-orchestrator and constructs a chat
request must explicitly select `auto`; fixed-mode exceptions are narrow,
path-scoped, and declared in `.cwl/contextual_orchestrator_policy.json`.
The workflow scans an exact target commit and checks out the scanner from an
explicit central commit. It has read-only contents permission, no repository
write step, and publishes bounded evidence only.

`auto` delegates topology to contextual-orchestrator: capability, quality, and
safety are satisfied before trustworthy known cost; absent or invalid prices
are unpriced, not free. The scanner is a regression guard, not a semantic
quality or SLO proof.

## Consequences

Consumers must call the reusable workflow with both the exact target commit and
the exact central governance commit. A deliberate fixed route requires a
reviewed path exception and separate benchmark/rollback evidence. The scanner
does not inspect tests, documentation, examples, migrations, or vendor code.

## References

See the repository-level adaptive consumer rule in [AGENTS.md](../../AGENTS.md) and the operational review-boundary record in [hourly-review-repair.md](../doctoring/hourly-review-repair.md).
