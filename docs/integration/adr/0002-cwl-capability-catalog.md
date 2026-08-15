# ADR-0002: Publish a federated capability and relationship catalogue

Status: Proposed

## Context

The shared envelopes define transport but do not identify product responsibility, authoritative ownership, permitted data flow, or deployment maturity. Prose-only mappings are easy to duplicate and overstate.

## Decision

Publish one organization-owned, machine-readable catalogue using closed JSON Schema Draft 2020-12 contracts. Leaf repositories retain domain semantics, persistence, runtime adapters, and release evidence. The validator rejects ambiguous ownership, unknown services, self-edges, direct cross-repository SQL, credential copying, raw PII broadcast, unversioned references, inferred-lineage authority, build controls carrying business data, and maturity claims beyond either endpoint.

Use package, independent-service, offline-scientific-worker, and build-operations-tool composition modes rather than forcing a universal HTTP topology.

## Consequences

### Positive

- Buyers and operators can discover the authoritative data owner and customer next action.
- Standalone products remain independently useful.
- Provider and consumer evidence can be promoted without a distributed monolith.
- Privacy-preserving opaque-reference flows replace blanket masking and raw PII broadcast.

### Costs

- Product teams must maintain exact contract and maturity evidence.
- The catalogue cannot infer implementation from documentation; promotions require protected evidence.
- Released schema corrections require a new version and explicit supersession.

## Rollback

Deprecate or supersede the catalogue revision and keep prior released schemas immutable. Preserve all no-direct-SQL, no-credential-copying, and no-raw-PII-broadcast controls.
