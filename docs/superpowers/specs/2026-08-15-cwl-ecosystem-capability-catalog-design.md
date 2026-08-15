# CWL Ecosystem Capability Catalogue v1 Design

Status: **Approved implementation baseline**

Owner: `ContextualWisdomLab/.github`

Depends on: CWL Ecosystem Integration Contract v1 (`.github` PR #1013)

Tracks: `.github` issue #1014

## Problem

The organization-level event and command envelopes define how CWL products may exchange information, but they do not answer which repository owns each product responsibility, which product is the authoritative data owner, what a consumer may receive, or what evidence is required before an integration is called implemented. That ambiguity creates buyer-visible risk: duplicated truth, direct cross-repository SQL, copied credentials, raw PII broadcast, and documentation that overstates deployment maturity.

## Decision

Publish two closed JSON Schema Draft 2020-12 contracts and one reviewed catalogue:

1. `cwl-service-capability-v1.schema.json` describes one product boundary.
2. `cwl-ecosystem-catalog-v1.schema.json` describes service-manifest references and purpose-bound relationships.
3. `cwl-ecosystem-catalog-v1.example.json` records the initial high-leverage CWL ecosystem without promoting planned or active-PR work to protected-main truth.

The catalogue references one bounded manifest per repository so product records remain independently reviewable. A modular standard-library validator enforces semantic invariants not expressible or intentionally not duplicated in JSON Schema. The validator is also the release-pipeline reference implementation; published schemas remain the interoperable contract and must still be validated by a conforming Draft 2020-12 implementation before release.

## Product boundary

The central `.github` repository owns organization vocabulary, catalogue schemas, the reviewed catalogue, validation, and compatibility guidance. Leaf repositories own domain semantics, operational databases, migrations, runtime adapters, release artifacts, and provider/consumer acceptance evidence.

The catalogue is not a global service registry that grants runtime authority. It is an architecture and deployment ledger.

## Service capability contract

Each service entry contains:

- `schema_version`
- `service_id`
- `repository`
- `product_boundary`
- `integration_mode`
- `maturity`
- `authority_domains`
- `consumer_repositories`
- `contracts`
- `database_ownership`
- `data_classifications`
- `released_artifacts`
- `next_actions`

`service_id`, authority-domain codes, purpose codes, and relationship IDs are lowercase two-or-more-word `snake_case`. Repository identity preserves GitHub's canonical case.

The allowed composition modes are exactly:

- `in_process_package`
- `independent_service`
- `offline_scientific_worker`
- `build_operations_tool`

## Relationship contract

Each relationship declares:

- provider service;
- consumer service;
- authoritative data owner;
- contract kind, semantic version, and immutable/versioned reference;
- purpose and data classification;
- allowed data-flow class;
- evidence class and whether the result may update an authoritative fact;
- maturity;
- explicit prohibitions on direct SQL, credential copying, and raw PII broadcast;
- success, rejection, timeout, duplicate, and rollback next actions.

Allowed data-flow classes are exactly:

- `reference_only`
- `purpose_bound_projection`
- `aggregate_artifact`
- `schema_contract`
- `no_business_data`
- `explicit_opt_in_projection`

## Maturity

The controlled maturity vocabulary is:

- `planned`
- `accepted_architecture`
- `active_pr`
- `implemented_on_protected_main`
- `released`
- `deprecated`
- `superseded`

An entry in a branch, issue, PRD, prototype, or conversation is not `implemented_on_protected_main`. Relationships may be less mature than their provider and consumer, but may not be more mature than either endpoint for `implemented_on_protected_main` or `released` claims.

## Security and privacy invariants

The validator fails closed when:

- any service or relationship permits direct cross-repository SQL;
- a relationship copies credentials;
- raw PII is broadcast;
- an inferred relationship is allowed to update authoritative truth;
- a build-control relationship carries business data;
- a no-business-data flow declares a business-data classification;
- a restricted-data relationship lacks purpose-bound, reference-only, aggregate, or explicit opt-in flow;
- a contract has no semantic version or immutable/versioned reference;
- a released artifact lacks a digest, Git commit, or versioned package/schema identity.

Blanket PII masking is not required. The design uses opaque references, authoritative-service lookup, workload identity, purpose-bound authorization, field-level protection, retention, revocation, and audit.

## Validation boundary

The CLI accepts one catalogue path and:

- requires a regular UTF-8 file no larger than 2 MiB;
- rejects duplicate JSON keys and non-finite numbers;
- limits structural depth, collection cardinality, and string length;
- rejects unknown top-level or nested properties;
- validates schema/constants alignment;
- resolves normalized `services/*.json` manifests without symlink or path escape;
- validates unique service IDs, manifest paths, repositories, relationship IDs, and released artifact IDs;
- rejects unknown service references and self-edges;
- applies the semantic security, ownership, and maturity invariants;
- emits one bounded operator-readable error and a non-zero exit status.

The validator does not execute repository code, resolve network references, fetch artifacts, or dereference PII.

## Initial catalogue

The reviewed initial catalogue covers:

- `.github`, naruon, Orgmetra, keyverse, contextual-orchestrator;
- psychometrics-commons, fast-mlsirm, TEPP;
- semantic-data-portal, OriginWeave, newsdom-api, RankWeave, ThreadWeave, EgressWeave, LineageWeave;
- inkspan, clearfolio;
- mhtml-etl-gateway, mightyETL, pg-erd-cloud;
- EmbedRelay, appguardrail, life-os, bandscope.

Entries remain deliberately conservative. Most cross-product integrations are `accepted_architecture` or `planned`; Orgmetra and the central catalogue are `active_pr` until protected integration.

## Quality contract

- Red-green-refactor TDD with a recorded test-only failing commit.
- Python standard library production implementation.
- Production statement coverage: 100%.
- Production branch coverage: 100%.
- Public module, class, and function docstrings: 100%.
- Python compilation and CLI positive/negative acceptance tests.
- Exact-head GitHub Actions workflow pinned to immutable action commits with `contents: read` only.
- No model credential, repository write authority, OIDC permission, external network lookup, or production dependency.
- Existing organization Security Scan, SAST, CodeQL, secret scanning, SBOM, provenance, and review gates remain mandatory.

## Rollout

1. Merge the event/command envelope PR #1013 normally.
2. Rebase or retarget this stacked catalogue PR onto protected `main` without changing its semantic contracts.
3. Publish the central schemas and catalogue after exact-head checks and independent approval.
4. Add one leaf capability manifest and one provider/consumer contract pair at a time.
5. Promote a relationship's maturity only after both repositories have released exact-version contract tests, authorization/idempotency evidence, and rollback evidence.

## Rollback

Rollback removes or deprecates a catalogue revision; it never restores direct SQL, credential copying, raw PII broadcast, or a false maturity claim. Released schemas are immutable. A replacement publishes a new version and records supersession.
