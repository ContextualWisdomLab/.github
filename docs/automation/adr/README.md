# Automation architecture decision records

Last reviewed: 2026-08-09

ADRs record durable decisions, not transient run status. A changed exact head, run ID, or provider outage belongs in traceability/incident evidence. Superseded ADRs remain in the index with their replacement.

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-branch-writer-leases-and-read-only-audit.md) | Branch-local writer leases and separate read-only fleet audit | Accepted |
| [ADR-0002](0002-exact-source-and-live-base-binding.md) | Exact source-head and independently resolved live-base binding | Accepted |
| [ADR-0003](0003-classified-bounded-retries.md) | Classified bounded retries with fail-closed permanent failures | Accepted |
| [ADR-0004](0004-explicit-secret-contracts.md) | Explicit minimal reusable-workflow secret contracts | Accepted |
| [ADR-0005](0005-independent-review-authority.md) | Counted independent review and stale-head semantics | Accepted |
| [ADR-0006](0006-protected-main-operational-acceptance.md) | Protected-main/consumer evidence closes operational incidents | Accepted |
| [ADR-0007](0007-work-conserving-maintenance.md) | Work-conserving automation; reporting is not completion | Accepted |
| [ADR-0008](0008-central-control-plane-and-thin-consumers.md) | Central control-plane ownership and thin product consumers | Accepted |
| [ADR-0009](0009-sandbox-evidence-redaction-boundary.md) | One complete sandbox evidence-redaction boundary with diagnostic preservation | Accepted; Draft clean-history integration proposed by [PR #906](https://github.com/ContextualWisdomLab/.github/pull/906); [PR #888](https://github.com/ContextualWisdomLab/.github/pull/888) closed unmerged as superseded evidence |
| [ADR-0010](0010-agent-mention-routing-and-idempotency-ledger.md) | Authenticated agent-mention routing with an idempotency ledger | Accepted |
| [ADR-0011](0011-provider-routing-and-credential-isolation.md) | Ordered provider routing with per-purpose credential isolation | Accepted |
| [ADR-0012](0012-hash-pinned-toolchains-and-exact-base-materialization.md) | Hash-pinned toolchains and independently resolved live-base identity | Accepted |
| [ADR-0013](0013-autofix-and-merge-authority-separation.md) | Separate autofix branch mutation from protected merge authority | Accepted |
| [ADR-0014](0014-trusted-metadata-event-and-default-branch-dispatch.md) | Keep privileged PR events metadata-only and execute validated work from protected source | Accepted |
| [ADR-0015](0015-direct-or-auto-merge-state-machine.md) | Ordered guarded direct merge with narrow native auto-merge fallback | Accepted |
| [ADR-0016](0016-fail-closed-security-gate-composition.md) | Compose independent live security/review authorities fail closed | Accepted |

## ADR quality contract

Every ADR includes context, drivers, alternatives, decision, consequences, failure/recovery, security/governance impact, tests/acceptance, migration/rollback, and supersession conditions. A decision that changes any of those sections requires an ADR update or replacement plus traceability and operational evidence.
