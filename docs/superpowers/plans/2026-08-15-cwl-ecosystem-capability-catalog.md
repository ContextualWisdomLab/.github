# CWL Ecosystem Capability Catalogue v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Preserve the recorded RED commit and verify every final claim on the exact candidate head.

**Goal:** Publish a strict repository-responsibility catalogue that prevents ambiguous authority, unsafe data flow, and false integration-maturity claims across CWL products.

**Architecture:** One closed service-capability schema, one closed catalogue schema, 24 independently reviewable service manifests, two conservative provider/consumer edges, modular standard-library validation, and a read-only exact-head quality workflow.

**Tech stack:** Python 3.14 standard library, JSON Schema Draft 2020-12 documents, pytest and coverage as hash-pinned test-only dependencies, GitHub Actions with immutable action pins.

## Global constraints

- Central `.github` owns vocabulary, schemas, catalogue, and reusable validation only.
- Leaf repositories own domain data, persistence, adapters, and release evidence.
- No direct cross-repository SQL, credential copying, or raw PII broadcast.
- Production statement and branch coverage are both 100%.
- Public module, class, and function docstrings are 100%.
- No model credential, repository write permission, OIDC permission, external fetch, or production dependency.
- Catalogue maturity distinguishes planned, accepted architecture, active PR, protected-main implementation, and release.

## Task 1 — Record RED contracts

- [x] Add the design and implementation-plan documents.
- [x] Add a test-only commit that imports the absent production validator.
- [x] Confirm the focused test fails before production code exists.

## Task 2 — Publish closed schemas and manifests

- [x] Add `schemas/cwl-service-capability-v1.schema.json`.
- [x] Add `schemas/cwl-ecosystem-catalog-v1.schema.json` with manifest references and relationship contracts.
- [x] Add 24 `schemas/examples/services/*.json` capability manifests.
- [x] Add the catalogue and service positive examples.
- [x] Keep integration maturity conservative; do not turn issues, branches, PRDs, or prototypes into protected-main claims.

## Task 3 — Implement bounded semantic validation

Production files:

- `scripts/ci/cwl_catalog_contract.py`
- `scripts/ci/cwl_catalog_io.py`
- `scripts/ci/cwl_catalog_service.py`
- `scripts/ci/cwl_catalog_relationship.py`
- `scripts/ci/validate_cwl_ecosystem_catalog.py`

- [x] Reject duplicate JSON keys, non-finite numbers, invalid UTF-8, non-regular inputs, oversized files, path escape, and symlink traversal.
- [x] Enforce bounded depth, cardinality, and string length.
- [x] Enforce exact object fields and controlled vocabularies.
- [x] Enforce unique services, repositories, manifest paths, contracts, artifacts, and relationships.
- [x] Enforce ownership, maturity, direct-SQL, credential, PII, inferred-lineage, build-control, and authoritative-write invariants.

## Task 4 — Add executable tests

Test files:

- `tests/catalogue_test_helpers.py`
- `tests/test_cwl_catalog_contract_and_io.py`
- `tests/test_cwl_catalog_services.py`
- `tests/test_cwl_catalog_relationships_cli_docs.py`

- [x] Cover strict I/O, primitive contracts, schema alignment, all 24 repositories, nested service records, graph invariants, CLI results, documentation, workflow contracts, and docstrings.
- [x] Require 100% production statement and branch coverage.

## Task 5 — Add documentation and doctoring

- [x] Add the federated responsibility map and closed-loop enterprise value chain.
- [x] Add ADR-0002, privacy design without blanket masking, maturity promotion, rollout, and rollback.
- [x] Add CSAP and SOC 2 engineering-readiness mapping without certification claims.
- [x] Add APA 7 references for JSON Schema, OpenAPI, AsyncAPI, CloudEvents, and PROV-O.
- [x] Link the envelope and catalogue contracts from `docs/integration/README.md`.
- [x] Update `[Unreleased]` in `CHANGELOG.md`.

## Task 6 — Add exact-head automation

- [x] Add path-scoped pull-request triggers.
- [x] Use `contents: read` only and disable credential persistence.
- [x] Pin checkout and setup-python by full commit SHA.
- [x] Install hash-verified test-only dependencies.
- [x] Verify exact source head, focused tests, 100% branch coverage, CLI acceptance, compilation, and clean diff.

## Task 7 — Verify and publish the stacked PR

- [x] Run 15 focused tests successfully.
- [x] Verify 359 production statements and 136 branches at 100%.
- [x] Validate the catalogue through the CLI.
- [x] Compile production and test modules.
- [x] Validate both schemas and positive instances with a conforming Draft 2020-12 implementation in the reconstructed local tree.
- [ ] Commit the GREEN tree and open a Draft PR based on `feat/cwl-ecosystem-integration-contract-v1`.
- [ ] After PR #1013 integrates, retarget or replay from protected `main`, rerun exact-head checks, resolve every review thread, obtain qualifying independent approval, and merge normally.
