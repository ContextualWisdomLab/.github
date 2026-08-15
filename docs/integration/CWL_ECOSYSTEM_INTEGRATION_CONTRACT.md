# CWL Ecosystem Integration Contract v1

Status: **Proposed organization contract**

Owner: `ContextualWisdomLab/.github`

Scope: interoperability rules shared by independently deployable ContextualWisdomLab products. Domain data models remain owned by the repository that owns the product responsibility.

## 1. Purpose

ContextualWisdomLab products must remain useful as standalone software while composing cleanly into a larger ecosystem. This contract defines the minimum API, event, command, provenance, identity-reference, temporal, privacy, and compatibility rules needed to connect independently versioned repositories without creating a distributed monolith.

The central `.github` repository owns this organization-wide transport and evidence profile. Leaf repositories own their domain semantics, persistence, business authorization, and release lifecycle.

## 2. Non-goals

This contract does **not**:

- make `.github` the source of truth for product-domain data;
- permit one service to read or mutate another service's application database directly;
- require every product to run as a network service;
- require raw personally identifiable information to be masked when an authorized workflow legitimately needs it;
- authorize an event or command merely because it validates against a schema;
- replace repository-local PRD, TRD, ADR, API, data model, security, or operability documentation;
- force experimental repositories to claim production maturity.

## 3. Composition modes

A CWL product may integrate through one or more of these modes:

1. **In-process package** — small, stateless, versioned calculation or transformation libraries.
2. **Independent service** — products with their own persistence, security boundary, scaling model, or lifecycle.
3. **Offline scientific worker** — research, validation, simulation, model fitting, and parity or recovery work.
4. **Build and operations tool** — CI, SAST, schema, release, provenance, and governance tooling.

A consumer must integrate through a versioned public interface. Git submodules and direct database access are not stable public interfaces.

## 4. Authority and ownership

### 4.1 Source-of-truth rule

Each business fact has exactly one authoritative owner. Other products may keep explicitly non-authoritative projections or immutable references.

Examples:

- identity credentials and federation belong to the identity product;
- mailbox, calendar, or file originals remain with the customer/provider that owns them;
- a domain system of record owns its business facts;
- a psychometric calculation engine owns computation artifacts, not the host application's user lifecycle;
- a catalog owns ontology/catalog records, not another product's operational entities;
- inferred lineage remains inference and must not silently become an authoritative audit fact.

### 4.2 No cross-service SQL

Independent services **MUST NOT** read or mutate another product's application tables. They integrate through:

- OpenAPI-described synchronous APIs;
- AsyncAPI-described channels where asynchronous messaging is used;
- CloudEvents-profiled domain events;
- explicitly versioned package interfaces;
- immutable artifact references.

### 4.3 Persistence

A service that owns durable state owns its migrations, backups, recovery, retention, and access controls. A consuming repository must not recreate a shadow authoritative copy merely to simplify integration.

## 5. Synchronous API profile

New shared HTTP APIs SHOULD use **OpenAPI 3.2.0**.

API rules:

- problem responses use **RFC 9457 Problem Details**;
- write operations use an `Idempotency-Key` where safe replay matters;
- distributed tracing propagates the stable W3C `traceparent`/`tracestate` contract;
- tenant, actor, purpose, and decision context are explicit and authorization-bound;
- authentication identifies the caller; it does not by itself authorize the requested domain action;
- opaque public identifiers are preferred over sequential database identifiers;
- API clients are generated or contract-tested from the owning service's published interface where practical.

A synchronous request that changes state carries, either in authenticated request context, headers, or a versioned request body:

```text
tenant_reference
actor_reference
purpose_code
decision_reference (when applicable)
idempotency_key
correlation_id
provenance_reference (when the request is evidence-backed)
```

## 6. Asynchronous event profile

CWL domain events use the **CloudEvents 1.0** data model. The organization profile is machine-readable in `schemas/cwl-event-envelope-v1.schema.json`.

The CloudEvents core attributes are the transport identity:

```json
{
  "specversion": "1.0",
  "id": "019c2d5d-f20a-7f8a-8d8e-4a5f6f5d5a41",
  "source": "https://github.com/ContextualWisdomLab/example-product",
  "type": "org.contextualwisdomlab.example.record.published.v1",
  "subject": "record_reference:example_123",
  "time": "2026-08-15T11:20:00Z",
  "datacontenttype": "application/json",
  "data": {}
}
```

CWL metadata lives under `data.metadata` rather than creating unconstrained top-level CloudEvents extensions. This gives the organization a versioned, contract-testable profile without redefining the CloudEvents data model.

Required CWL metadata:

```text
event_version
tenant_id
subject_reference
purpose_code
occurred_at
recorded_at
correlation_id
provenance_reference
data_classification
```

Optional but standardized metadata:

```text
available_at
causation_id
decision_reference
actor_reference
traceparent
```

Semantic invariants that JSON Schema alone does not express:

- CloudEvents `id` is the same logical identifier as the event receipt identifier and is a UUIDv7.
- CloudEvents `time` equals `data.metadata.occurred_at`.
- CloudEvents `subject` equals `data.metadata.subject_reference`.
- `recorded_at` is system-observation time; `occurred_at` is business/event time.
- `available_at`, when present, is when the evidence became usable by the receiving analytical or decision workflow.
- `causation_id`, when present, references the immediate predecessor command/event that caused this event.
- `correlation_id` remains stable across one business workflow.
- `provenance_reference` points to evidence or provenance owned by an authorized source, not an unverified free-text explanation.
- validation is necessary but never sufficient for authorization.

## 7. Command profile

Asynchronous commands use `schemas/cwl-command-envelope-v1.schema.json`. Commands are intent, not fact.

A command includes:

```text
command_id
command_type
command_version
tenant_id
actor_reference
subject_reference
purpose_code
requested_at
idempotency_key
correlation_id
provenance_reference
data_classification
payload
```

`causation_id`, `decision_reference`, and `traceparent` are standardized optional fields.

Command handlers MUST:

1. authenticate the caller;
2. authorize tenant, actor, subject, purpose, action, and resource;
3. enforce idempotency;
4. validate the current domain state;
5. execute or fail closed;
6. emit a domain event only after the authoritative state transition commits;
7. retain sufficient audit/provenance evidence for the owning product's policy.

## 8. Temporal semantics

CWL integrations distinguish at least:

- **occurred_at** — when the business event happened or became valid;
- **recorded_at** — when the owning system recorded or observed it;
- **available_at** — when the evidence was available to a downstream analytical/decision workflow, when materially different.

A temporal/analytical product MUST prevent future-information leakage by applying its own knowledge-cutoff rule to `available_at` rather than backdating later evidence to the historical event date.

Products with stronger temporal requirements may add valid-time/system-time interval contracts in their own schema without redefining these shared meanings.

## 9. Identity, PII, and privacy

CWL does **not** adopt blanket PII masking as an interoperability strategy.

Instead:

- broadcast/event payloads default to opaque subject references and the minimum attributes required for the receiving purpose;
- a service with a legitimate purpose may dereference authorized PII through the authoritative API;
- authorization is purpose-bound, tenant-bound, resource-bound, and audited;
- raw credentials, session tokens, API keys, and authentication secrets never belong in domain events;
- raw PII in asynchronous payloads requires an explicit repository-local threat/privacy decision, topic ACLs, encryption, retention rules, and access/export logging;
- model traces receive only the minimum data needed for the approved operation;
- de-identification or pseudonymization is used where analytically sufficient, but never misrepresented as eliminating re-identification risk.

## 10. Provenance and traceability

W3C PROV-O is the semantic reference for representing provenance relationships where a graph representation is needed. The shared envelope uses `provenance_reference` so products can link to their own provenance store without copying the entire graph onto the message bus.

The minimum provenance chain for a derived artifact SHOULD identify:

```text
source evidence
→ transformation or computation
→ software/model version
→ output artifact
→ verification/review state
```

The provenance record must distinguish authoritative facts, inferred relationships, model judgments, and operator approvals.

## 11. Schema and compatibility rules

- JSON contracts use **JSON Schema Draft 2020-12**.
- Event transport follows CloudEvents **specversion `1.0`**.
- Async channel descriptions use **AsyncAPI 3.1.0** when a repository publishes asynchronous interfaces.
- Synchronous APIs use **OpenAPI 3.2.0** for new shared contracts unless a consumer compatibility constraint is documented.
- HTTP error payloads use **RFC 9457**.
- New organization-level event/command/correlation identifiers use **RFC 9562 UUIDv7** where time-ordered globally unique identifiers are beneficial.
- Stable distributed-trace propagation follows the W3C Trace Context Recommendation. The v1 JSON envelopes deliberately accept version `00` traceparents only and reject all-zero trace IDs, all-zero parent IDs, and forbidden version `ff`; future Trace Context versions require a new profile revision rather than silent widening.
- Breaking contracts require a new major version or a parallel endpoint/channel/schema; consumers are not silently migrated.
- Producers and consumers both maintain contract tests for interfaces they depend on.
- A producer does not declare a breaking interface safe solely because its own tests pass.
- Schema registry paths and artifact digests are immutable for released versions.

## 12. Event type naming

Event types use:

```text
org.contextualwisdomlab.<bounded_context>.<entity_or_concept>.<past_tense_event>.v<major>
```

Example:

```text
org.contextualwisdomlab.psychometrics.assessment_result.published.v1
```

Commands use:

```text
org.contextualwisdomlab.<bounded_context>.<entity_or_concept>.<imperative>.v<major>
```

Example:

```text
org.contextualwisdomlab.identity.account.provision.v1
```

Each segment after `org.contextualwisdomlab` uses lowercase `snake_case`; empty segments, hyphenated segments, and version zero are invalid.

Event names describe facts that have happened. Command names describe requested actions.

## 13. Database projection rules

Transport schemas are not database schemas.

When a receiving service persists a projection:

- its database remains normalized to at least third normal form for authoritative relational data unless an accepted ADR documents a deliberate read-model exception;
- owned database objects use descriptive `snake_case` names containing at least two words;
- external event identifiers, source references, and schema versions are stored separately from business-domain primary keys;
- raw transport envelopes may be retained only under an explicit audit/retention policy;
- a projection is labelled non-authoritative unless that service is the domain owner.

## 14. Security and compliance evidence

Integration features are designed for SOC 2 and CSAP evidence readiness without claiming certification.

Every production integration SHOULD be able to demonstrate:

- caller/service identity and authorization boundary;
- least-privilege credentials;
- data classification and purpose;
- encryption in transit and at rest where applicable;
- retention and deletion behavior;
- access/export auditability;
- schema/version compatibility evidence;
- dependency/SBOM/provenance evidence;
- retry, duplicate, timeout, and degraded-mode behavior;
- rollback/recovery procedure;
- exact-source release evidence.

## 15. Repository adoption sequence

A leaf repository adopting v1 should:

1. document its bounded context and source-of-truth ownership;
2. identify existing inbound/outbound APIs, commands, events, packages, and artifacts;
3. map them to the v1 envelopes without changing domain ownership;
4. add provider and consumer contract tests;
5. add OpenAPI/AsyncAPI/JSON Schema artifacts only for interfaces it actually implements;
6. document PII classification and dereference policy;
7. document degraded, retry, idempotency, recovery, and version-migration behavior;
8. update its ADR/Architecture/Traceability/CHANGELOG;
9. roll out one bounded integration at a time.

## 16. Organization-level acceptance

An inter-repository integration is not complete until evidence exists for the same released contract version on both sides:

```text
producer schema
+ producer test
+ consumer test
+ authorization test
+ idempotency/retry test
+ provenance evidence
+ degraded/recovery test
+ exact released artifact identities
```

Queued, skipped, stale-head, predecessor-version, or model-only evidence does not satisfy the contract.
