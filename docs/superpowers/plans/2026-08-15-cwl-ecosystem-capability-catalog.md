# CWL Ecosystem Capability Catalogue v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a strict, machine-readable repository responsibility catalogue that prevents ambiguous authority, unsafe data flow, and false integration-maturity claims across CWL products.

**Architecture:** Two closed Draft 2020-12 schemas define service capabilities and provider/consumer relationships. A standard-library Python validator enforces bounded parsing and cross-record semantic invariants; a reviewed catalogue and exact-head workflow provide executable organization evidence.

**Tech Stack:** Python 3.14 standard library, JSON Schema Draft 2020-12 documents, pytest/coverage as test-only dependencies, GitHub Actions with immutable action pins.

## Global Constraints

- Central `.github` owns vocabulary, schemas, catalogue, and reusable validation only.
- Leaf repositories own domain data, persistence, adapters, and release evidence.
- No direct cross-repository SQL, credential copying, or raw PII broadcast.
- Database object identifiers use descriptive two-or-more-word `snake_case`.
- Production statement and branch coverage are both 100%.
- Public module/class/function docstrings are 100%.
- No model credential, repository write permission, OIDC, external fetch, or production dependency.
- Catalogue maturity must distinguish planned, accepted architecture, active PR, protected-main implementation, and released state.

---

### Task 1: Record the executable contract tests

**Files:**
- Create: `tests/test_cwl_ecosystem_catalog.py`
- Create: `docs/superpowers/specs/2026-08-15-cwl-ecosystem-capability-catalog-design.md`
- Create: `docs/superpowers/plans/2026-08-15-cwl-ecosystem-capability-catalog.md`

**Interfaces:**
- Consumes: issue #1014 and PR #1013 envelope vocabulary.
- Produces: required constants and CLI behavior for `scripts/ci/validate_cwl_ecosystem_catalog.py`.

- [ ] **Step 1: Write tests that import the absent validator and specify strict parsing, schema alignment, graph integrity, security invariants, maturity rules, CLI behavior, and docstrings.**
- [ ] **Step 2: Run `python -m pytest -q tests/test_cwl_ecosystem_catalog.py` and confirm collection fails because the production module does not exist.**
- [ ] **Step 3: Commit the test-only RED state with message `test(integration): specify ecosystem catalogue contract`.**

### Task 2: Add closed schemas and the initial catalogue

**Files:**
- Create: `schemas/cwl-service-capability-v1.schema.json`
- Create: `schemas/cwl-ecosystem-catalog-v1.schema.json`
- Create: `schemas/examples/cwl-service-capability-v1.example.json`
- Create: `schemas/examples/cwl-ecosystem-catalog-v1.example.json`

**Interfaces:**
- Consumes: controlled enum constants asserted by Task 1.
- Produces: Draft 2020-12 service and catalogue contracts loaded by the validator.

- [ ] **Step 1: Add closed schemas with exact required fields and controlled enums.**
- [ ] **Step 2: Add a conservative 24-service catalogue and purpose-bound relationship set.**
- [ ] **Step 3: Run schema-alignment and positive-fixure tests; confirm remaining tests fail only because the validator is absent.**

### Task 3: Implement bounded semantic validation

**Files:**
- Create: `scripts/ci/validate_cwl_ecosystem_catalog.py`
- Test: `tests/test_cwl_ecosystem_catalog.py`

**Interfaces:**
- Consumes: one filesystem path to the catalogue JSON.
- Produces: `validate_catalog(path: pathlib.Path) -> None` and `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Implement a duplicate-key/non-finite rejecting JSON decoder with regular-file, UTF-8, and 2 MiB limits.**
- [ ] **Step 2: Implement bounded recursive shape checks and exact property sets.**
- [ ] **Step 3: Implement service, contract, artifact, relationship, ownership, security, and maturity invariants.**
- [ ] **Step 4: Run focused tests until all pass.**
- [ ] **Step 5: Run branch coverage with `python -m coverage run --branch -m pytest -q  tests/test_cwl_ecosystem_catalog.py` and require 100% for the production module.**

### Task 4: Add organization documentation and doctoring

**Files:**
- Create: `docs/integration/CWL_REPOSITORY_RESPONSIBILITY_CATALOG.md`
- Create: `docs/integration/adr/0002-cwl-capability-catalog.md`
- Create: `docs/doctoring/ecosystem-capability-catalog-standards.md`
- Modify: `docs/integration/CWL_ECOSYSTEM_INTEGRATION_CONTRACT.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: schemas, validator, and initial catalogue.
- Produces: buyer/operator next actions, rollout/rollback rules, diagrams, CSAP/SOC 2 engineering mapping, and APA 7 references.

- [ ] **Step 1: Document the federated responsibility map and closed-loop enterprise value chain.**
- [ ] **Step 2: Record the ADR, privacy alternative to blanket masking, maturity promotion rules, and rollback.**
- [ ] **Step 3: Add APA 7 references to the primary specifications already used by the central profile.**
- [ ] **Step 4: Link the catalogue from the envelope contract and update `[Unreleased]`.**

### Task 5: Add exact-head quality automation

**Files:**
- Create: `.github/workflows/cwl-ecosystem-catalog-quality-ci.yml`

**Interfaces:**
- Consumes: exact PR head, test file, validator, schemas, catalogue, and documentation.
- Produces: one read-only quality check with 100% statement/branch coverage and compilation evidence.

- [ ] **Step 1: Add path-scoped PR triggers and `contents: read` permissions.**
- [ ] **Step 2: Pin checkout and setup-python by full commit SHA.**
- [ ] **Step 3: Install hash-verified test-only dependencies.**
- [ ] **Step 4: Verify exact HEAD, focused tests, 100% branch coverage, CLI validation, compilation, and clean diff.**

### Task 6: Verify and publish the stacked PR

**Files:**
- All files from Tasks 1–5.

**Interfaces:**
- Consumes: exact local/reconstructed tree.
- Produces: Draft PR based on `feat/cwl-ecosystem-integration-contract-v1`.

- [ ] **Step 1: Run focused pytest and coverage commands from a clean reconstructed tree.**
- [ ] **Step 2: Run `python -m compileall -q scripts/ci/validate_cwl_ecosystem_catalog.py tests/test_cwl_ecosystem_catalog.py`.**
- [ ] **Step 3: Run the CLI against the published catalogue.**
- [ ] **Step 4: Scan for placeholders, unbalanced Markdown fences, unknown catalogue repositories, and noncanonical identifiers.**
- [ ] **Step 5: Commit GREEN implementation and open a Draft stacked PR with exact-head evidence and dependency order.**
