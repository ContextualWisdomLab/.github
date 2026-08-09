# Automation control-plane documentation

Status: active_pr

This directory is the canonical documentation graph for the organization automation control plane. It separates shipped behavior, active work, accepted architecture, plans, research, superseded decisions, and out-of-scope proposals. Pull-request bodies, conversational history, automation prompts, and downloadable planning artifacts are evidence inputs, not the durable specification.

The control plane spans three distinct authorities: external scheduled agent/orchestrator state, GitHub execution/evidence/policy state, and this canonical documentation graph. A durable decision is reconciled here only after live implementation and active ownership are refetched; product-specific specifications remain in their owning repositories.

## Canonical documents

- [Product requirements](PRD.md)
- [Technical requirements](TRD.md)
- [Architecture](ARCHITECTURE.md)
- [Conceptual data model](DATA_MODEL.md)
- [UML diagrams](UML.md)
- [Security](SECURITY.md)
- [Threat model](THREAT_MODEL.md)
- [Test strategy](TEST_STRATEGY.md)
- [Operability](OPERABILITY.md)
- [Incident runbook](INCIDENT_RUNBOOK.md)
- [Traceability](TRACEABILITY.md)
- [Documentation fitness audit](DOCUMENTATION_AUDIT.md)
- [Architecture decision records](adr/README.md)

## Status vocabulary

Every canonical document declares exactly one status:

- `implemented_on_protected_main`: directly verified on the current protected branch.
- `active_pr`: proposed by an open pull request and not yet shipped.
- `accepted_architecture`: accepted direction whose implementation may be incomplete.
- `planned`: approved backlog without implementation evidence.
- `research_only`: exploratory material that does not authorize production behavior.
- `superseded`: retained only for historical traceability.
- `out_of_scope`: explicitly excluded from the control plane.

## Change discipline

A behavioral change updates requirements, architecture, security, tests, operations, traceability, documentation fitness, and affected ADRs in the same integration line. Exact commit identities belong in dated evidence or pull-request records, not timeless architecture. Operational incidents close only after protected-main consumer evidence proves the repaired boundary.

A prompt update or documentation update is not run completion when another safe executable lane exists. After canonical documentation mutation, the authoritative writer returns to the live executable queue and applies the continuation/exit-sweep contract in ADR-0003 and ADR-0010.
