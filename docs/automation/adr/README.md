# Architecture decision records

These ADRs are the minimum durable decision set for the CWL automation control
plane. An accepted ADR records policy and design intent; its implementation
state is separately identified in the ADR and in
[../DOCUMENTATION_COVERAGE.md](../DOCUMENTATION_COVERAGE.md). New evidence may
supersede an ADR, but must not silently rewrite its historical decision.

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](0001-writer-lease-and-read-only-fleet-auditor.md) | One branch writer lease; fleet audit remains read-only | Accepted |
| [ADR-0002](0002-exact-head-and-live-base-binding.md) | Bind evidence to exact source head and independently observed live base | Accepted |
| [ADR-0003](0003-classified-bounded-retries.md) | Retry only classified transient failures within a fixed budget | Accepted |
| [ADR-0004](0004-minimal-reusable-workflow-secrets.md) | Reusable workflows use explicit minimal secret interfaces | Accepted; migration in progress |
| [ADR-0005](0005-independent-review-governance.md) | Keep advisory automation separate from counted independent approval | Accepted |
| [ADR-0006](0006-protected-main-operational-closure.md) | Operational incidents close only after protected-main consumer evidence | Accepted |
| [ADR-0007](0007-work-conserving-automation.md) | Local waits defer one item; the automation continues another safe lane | Accepted |
| [ADR-0008](0008-central-control-plane-thin-leaf-contract.md) | Centralize privileged policy and keep leaf integrations thin | Accepted |

## Lifecycle

1. **Proposed:** reviewable decision with explicit alternatives and migration.
2. **Accepted:** governing decision; not necessarily fully implemented.
3. **Superseded:** retained for history and linked to its replacement.
4. **Rejected:** retained when its reasoning is useful.

Implementation evidence belongs in code, tests, exact-head checks, and
protected-main consumer receipts, not in an ADR status label alone.
