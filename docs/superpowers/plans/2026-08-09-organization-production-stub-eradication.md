# Organization Production Stub Eradication Implementation Plan

> **Status: CURRENT (cadence reconciled, 2026-08-12).** The accepted operational
> contract scans one stable SHA-256-assigned twelfth every hour at minute 17,
> completes the fleet twice per day, and keeps
> `max-parallel: 4`; repository-dispatch remains the full-fleet replay path.
> Current authority is
> `.github/workflows/organization-production-stub-scan.yml`,
> `tests/test_organization_production_stub_workflow.py`, and
> `docs/doctoring/production-stub-eradication-references.md`.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every success-shaped demo, mock, placeholder, and advertised-but-unimplemented production path across ContextualWisdomLab repositories and prevent recurrence.

**Architecture:** A central multi-language scanner inventories exact default-branch commits with hourly stable SHA-256 sharding and bounded four-repository parallelism, completing two fleet cycles per day while preserving exact-SHA evidence for every finding. When a repository supports Issues, the workflow maintains one remediation issue per affected repository; when Issues are disabled, the failed exact-SHA artifact remains the durable remediation evidence without an impossible issue mutation. Repository owners then replace each finding with a real provider-backed implementation or remove the unsupported capability, using fail-first tests and exact-head quality gates. Declaration-only Protocol/ABC/overload contracts, tests, fixtures, examples, generated code, and vendor code remain outside the production finding set.

**Tech Stack:** Python 3 AST and deterministic regex scanning, GitHub Actions, GitHub REST API through `gh`, JSON evidence schema, repository-native test and coverage tools.

## Global Constraints

- Scan every tracked runtime source file at an exact 40-character commit SHA.
- Never treat queued, absent, skipped-required, stale-head, or failed evidence as passing.
- Never turn a production stub into a success-shaped no-op.
- Preserve declaration contracts for Python Protocol, ABC, abstract methods, and overloads.
- Exclude tests, fixtures, examples, documentation, generated outputs, dependencies, and vendored code.
- Require a fail-first regression before production implementation changes.
- Require production statement and branch coverage of 100% for changed product modules.
- Require public API docstrings of 100% for changed product modules.
- Update CHANGELOG, operator documentation, and doctoring references with each product remediation.
- Use exact repository/base/head identities in issues, pull requests, and evidence artifacts.
- Keep scheduled fleet work bounded so the completeness gate cannot become a competing organization Actions availability defect.
- Run one stable SHA-256-assigned twelfth at minute 17 every hour; retain minute 17 to avoid the top-of-hour scheduled-workflow spike and keep repository-dispatch as the full-fleet replay path.
- Do not use `COPILOT_GITHUB_TOKEN`; LLM remediation workflows use `NVIDIA_NIM_API_KEY` when an LLM is actually required.

---

### Task 1: Multi-language production-stub inventory

**Files:**
- Create: `scripts/ci/organization_production_stub_scan.py`
- Create: `tests/test_multilanguage_stub_scan.py`
- Reuse: `scripts/ci/implementation_completeness_scan.py`

**Interfaces:**
- Consumes: repository root plus either `--all-tracked` or `--changed-files <path>`.
- Produces: Markdown or JSON report using schema `cwl.implementation-completeness/v2`; exit code 1 for findings or parse errors.

- [x] **Step 1: Write failing tests for JS/TS, Go, runtime markers, demo success paths, exclusions, exact Git inventory, JSON determinism, and CLI inventory exclusivity.**

- [x] **Step 2: Run `pytest -q tests/test_multilanguage_stub_scan.py` and verify failures identify the absent scanner API.**

- [x] **Step 3: Implement supported-path classification, NUL-delimited tracked-file discovery, Python/Rust reuse, cross-language high-confidence findings, deterministic ordering, bounded suppression, and report rendering.**

- [x] **Step 4: Run `pytest -q tests/test_multilanguage_stub_scan.py tests/test_implementation_completeness_scan.py` and `python -m py_compile scripts/ci/organization_production_stub_scan.py`.**

- [x] **Step 5: Commit scanner and tests as reviewable units.**

### Task 2: Hourly stable-shard exact-SHA organization inventory

**Files:**
- Create: `.github/workflows/organization-production-stub-scan.yml`
- Create: `tests/test_organization_production_stub_workflow.py`

**Interfaces:**
- Consumes: organization repository inventory, exact default-branch revisions, repository Issues capability, and `PR_REVIEW_MERGE_TOKEN` only for supported remediation-issue mutation.
- Produces: one exact-SHA JSON artifact per repository; one bounded remediation issue per non-clean repository when Issues are enabled; otherwise a failed exact-SHA artifact and explicit issue-disabled boundary without attempting issue mutation.

- [x] **Step 1: Write a failing workflow contract test for bounded fleet cadence and exact identities.**

```python
assert 'cron: "17 * * * *"' in workflow
assert "SHARD_COUNT: '12'" in workflow
assert "max-parallel: 4" in workflow
assert "ref: ${{ matrix.repository_sha }}" in workflow
assert "ref: ${{ github.sha }}" in workflow
assert "--all-tracked" in workflow
```

- [x] **Step 2: Run `pytest -q tests/test_organization_production_stub_workflow.py` and verify the contract fails before the cadence/capability repair.**

- [x] **Step 3: Implement exact default-branch SHA discovery, hourly stable-twelfth scheduling at minute 17, bounded four-repository parallelism, immutable central scanner checkout, full-fleet repository-dispatch replay, artifact upload, issue create/update and clean-rescan closure only when `has_issues` is true, explicit Issues-disabled artifact-only remediation, and preserved failing conclusion.**

- [ ] **Step 4: Run the complete central test suite and actionlint on the exact pull-request head.**

Run:

```bash
pytest -q
python -m py_compile scripts/ci/organization_production_stub_scan.py
actionlint .github/workflows/organization-production-stub-scan.yml
```

Expected: all tests pass, compilation succeeds, actionlint reports no errors, the live cron is `17 * * * *`, scheduled runs select one of twelve stable shards, and repository-dispatch selects the complete eligible fleet.

- [ ] **Step 5: Merge only after current-head required checks and independent approval pass.**

### Task 3: ScopeWeave checkout remediation

**Files:**
- Modify: `server/billing.mjs`
- Create: `tests/unit/billing-configuration.test.mjs`
- Modify: `package.json`
- Modify: `docs/deploy.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: complete Stripe secret-key and Price configuration, organization ID, trusted request origin.
- Produces: a Stripe-hosted Checkout URL or a stable fail-closed billing error; a mock URL only when `SCOPEWEAVE_DEV=1`.

- [x] **Step 1: Write a failing regression showing unconfigured production checkout must not return `billing=mock`.**

- [x] **Step 2: Verify the regression fails because the current implementation returns a mock success response.**

- [x] **Step 3: Implement Checkout Sessions using a server-side form POST, idempotency key, provider response validation, trusted checkout-host validation, and explicit error codes.**

- [x] **Step 4: Add complete provider-boundary tests and include `server/billing.mjs` in production coverage.**

- [ ] **Step 5: Update deployment documentation and CHANGELOG, then run unit, API, coverage, fuzz, and E2E suites.**

Run:

```bash
npm ci
npm run test:unit
npm run test:api
npm run coverage
npm run fuzz
npm run test:e2e
```

Expected: every command succeeds; production statement and branch coverage remain 100%.

### Task 4: ScopeWeave signed subscription lifecycle

**Files:**
- Create: `server/stripe-webhook.mjs`
- Create: `tests/unit/stripe-webhook.test.mjs`
- Modify: `server/app.mjs`
- Modify: `server/db.mjs`
- Modify: `docs/deploy.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: raw request bytes, `Stripe-Signature`, `STRIPE_WEBHOOK_SECRET`, event ID, subscription/customer/status metadata.
- Produces: idempotent billing-event receipt and server-authoritative organization entitlement transition.

- [ ] **Step 1: Write failing tests for absent signature, altered payload, stale timestamp, duplicate event, wrong organization metadata, completed checkout, subscription update, cancellation, and provider retry.**

- [ ] **Step 2: Verify current unsigned JSON handler fails the tests by accepting untrusted events.**

- [ ] **Step 3: Implement HMAC signature verification over exact raw bytes, bounded timestamp tolerance, constant-time comparison, event-id deduplication, and a two-word `billing_event_record` database object.**

- [ ] **Step 4: Replace the inline stub route with the verified handler; never expose secrets or raw provider payloads in responses/logs.**

- [ ] **Step 5: Run the full ScopeWeave verification commands from Task 3 and exact-head security checks.**

### Task 5: Naruon DAV capability truthfulness

**Files:**
- Modify: `backend/api/dav.py`
- Modify: `backend/tests/test_dav_sync.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: authenticated WebDAV discovery and PROPFIND requests.
- Produces: only genuinely supported methods in `Allow` and `DAV` headers; unsupported verbs receive a framework-level 405 response.

- [ ] **Step 1: Write failing tests proving OPTIONS must not advertise GET, PUT, DELETE, MKCOL, COPY, MOVE, LOCK, UNLOCK, REPORT, or PROPPATCH while handlers only return 501.**

- [ ] **Step 2: Run the focused test and observe the over-advertised method list.**

- [ ] **Step 3: Restrict route registration and OPTIONS output to real capabilities, delete dead success/501 branches, and preserve PROPFIND behavior.**

- [ ] **Step 4: Run focused API tests, full backend tests, statement/branch coverage, type checks, and security checks.**

### Task 6: Naruon WebDAV demo state removal

**Files:**
- Modify: `backend/services/webdav_service.py`
- Modify: `backend/tests/test_webdav_api.py`
- Modify: `backend/tests/test_dav_sync.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: tenant/workspace-scoped database session and encrypted provider credentials.
- Produces: database/provider-authoritative account, folder, and writeback operations; never hard-coded `demo_user`, mock accounts, or success-shaped no-op writes.

- [ ] **Step 1: Write failing tests that reject mock account/folder inventory and no-op attachment writeback.**

- [ ] **Step 2: Prove the legacy synchronous methods are unused by production callers; remove them when no compatibility contract exists.**

- [ ] **Step 3: Where a contract is public, route it through the existing `*_from_db` and provider execution path with tenant authorization and audit evidence.**

- [ ] **Step 4: Run full backend and connector integration verification.**

### Task 7: Fleet remediation waves

**Files:**
- Per finding: production module, focused regression, CHANGELOG, operator documentation, applicable ADR/doctoring references.

**Interfaces:**
- Consumes: the exact-SHA inventory generated by Task 2 and its optional remediation issue.
- Produces: a bounded pull request that replaces or removes every listed production stub; when Issues are enabled, closes the inventory issue only after a clean default-branch rescan.

- [ ] **Step 1: Process findings in risk order: authentication/authorization, billing, data loss/writeback, external providers, schedulers, user-visible fake results, then dead advertised APIs.**

- [ ] **Step 2: For each repository, write one fail-first regression per behavior and verify the expected failure.**

- [ ] **Step 3: Implement the narrowest real behavior or remove the unsupported capability from routing, UI, OpenAPI, docs, and permissions.**

- [ ] **Step 4: Run repository-native full verification, inspect every review thread and required check, and merge only exact-head clean changes.**

- [ ] **Step 5: Rerun the central all-tracked scanner; require a clean exact default-branch artifact and, where supported, automatic remediation-issue closure.**

## Self-review

- Spec coverage: all-tracked discovery, multi-language detection, exact SHA evidence, bounded Korean off-peak daily fleet load, Issues capability, durable remediation, fail-first replacement, repository-specific first waves, documentation, and merge gates are mapped to tasks.
- Placeholder scan: this plan contains no `TBD`, deferred implementation shorthand, or unspecified test instruction.
- Type consistency: scanner schema, CLI flags, workflow matrix fields, and finding fields are identical across Tasks 1–2.
