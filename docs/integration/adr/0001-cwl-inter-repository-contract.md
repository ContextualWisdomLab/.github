# ADR-0001: Organization-wide inter-repository integration contract

- Status: Proposed
- Date: 2026-08-15
- Decision owner: ContextualWisdomLab organization control plane
- Scope: Cross-repository public interfaces

## Context

ContextualWisdomLab contains independently useful products with different ownership, persistence, release, and security boundaries. Without a shared integration contract, the ecosystem can drift toward direct database coupling, duplicated domain truth, inconsistent event metadata, non-auditable model handoffs, and incompatible identity/tenant/time semantics.

The repository name alone is not an architectural boundary. The correct integration owner is determined by product responsibility, source-of-truth ownership, reuse boundary, existing implementation, and consuming repositories.

## Considered options

### A. Copy shared domain models into every repository

Rejected. This creates divergent truth, synchronized release requirements, and a distributed monolith.

### B. Make every reusable component an HTTP microservice

Rejected. Stateless libraries and scientific kernels do not gain value from forced network boundaries, and the result would add failure domains and operational cost.

### C. Federated composition with a shared transport/evidence profile

Accepted.

- stateless libraries may remain packages;
- products with independent state/lifecycle remain services;
- scientific validation may run as offline workers;
- build/security tooling remains tooling;
- cross-service interfaces use versioned API/event/command/artifact contracts;
- domain ownership never moves merely because another repository consumes a fact.

## Decision

Adopt `docs/integration/CWL_ECOSYSTEM_INTEGRATION_CONTRACT.md` and the v1 JSON Schemas as the organization profile.

The profile uses:

- OpenAPI 3.2.0 for new shared synchronous APIs;
- AsyncAPI 3.1.0 for published asynchronous channel contracts;
- CloudEvents 1.0 for domain-event transport;
- JSON Schema Draft 2020-12 for JSON payload contracts;
- RFC 9457 for HTTP problem details;
- RFC 9562 UUIDv7 for organization-level time-ordered identifiers where appropriate;
- W3C Trace Context Recommendation version `00` grammar for the v1 envelope, rejecting forbidden all-zero trace and parent identifiers;
- W3C PROV-O as the provenance semantic reference.

CWL-specific metadata is placed inside `data.metadata` for domain events rather than inventing unrestricted top-level CloudEvents extensions.

## Consequences

### Positive

- standalone products remain independently deployable;
- consumers can rely on shared tenant, purpose, causation, temporal, and provenance semantics;
- raw PII need not be broadcast merely to connect services;
- authorized services may still retrieve necessary PII from the authoritative owner;
- provider and consumer contract tests become a concrete merge/release gate;
- ecosystem diagrams and connectors can be generated from public contracts instead of repository-name assumptions.

### Costs

- producers must publish and version interfaces;
- consumers must maintain contract tests;
- adapters are required for legacy interfaces;
- some duplicated metadata is deliberate, such as CloudEvents `time`/`subject` mirrored by explicit CWL business metadata, and implementations must test semantic equality.

## Failure and recovery

If a producer emits a non-conforming or unsupported major version, consumers fail closed or quarantine the message according to their local operability contract. They must not coerce unknown fields into an older semantic meaning.

Rollback keeps the prior compatible interface available until all required consumers have migrated or a documented compatibility window ends.

## Security and governance impact

Schema validation is not authorization. Services still enforce tenant, actor, purpose, subject, action, resource, and credential policy.

Event buses default to opaque references and data minimization. Raw PII may be processed under a legitimate authorized purpose, but its asynchronous replication requires explicit security/privacy controls.

Direct cross-service application-database access is prohibited.

## Verification

The central repository includes stdlib-only contract tests that validate:

- required profile artifacts exist and are parseable;
- complete positive examples satisfy the supported JSON Schema subset used by the v1 profiles;
- unknown top-level properties and invalid trace identifiers fail closed;
- CloudEvents `specversion` is pinned to `1.0`;
- JSON Schemas use Draft 2020-12;
- examples contain the required CWL metadata;
- UUIDv7, bounded event/command type names, and W3C Trace Context version `00` constraints are enforced;
- documentation names the current authoritative external standards.

Leaf repositories add producer/consumer contract tests when they adopt the profile. Before release, published schemas are also checked with a conforming JSON Schema Draft 2020-12 implementation in the release pipeline.

## Supersession

A future ADR may supersede this decision only with:

- explicit migration and rollback rules;
- compatibility impact on existing consumers;
- updated machine-readable schemas;
- updated standards/doctoring evidence.
