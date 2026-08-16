# Test strategy — CWL automation control plane

Status: accepted baseline
Last reviewed: 2026-08-09

## 1. Quality policy

Testing must prove authority and failure behavior, not merely execute happy paths. Production changes are test-first when feasible, public Python interfaces have beginner-readable docstrings, and owned production code must reach 100% statement and branch coverage. Coverage is necessary but does not replace realistic integration, security, concurrency, compatibility, or protected-main tests.

Every hosted result is bound to the exact head that produced it. A new commit makes predecessor results historical.

## 2. Test layers

| Layer | Purpose | Examples |
|---|---|---|
| Pure unit | Parsing, normalization, classification, state transitions | evidence schemas, redaction tokens, retry classes, reviewer eligibility |
| Contract | Lock workflow events, permissions, names, inputs, secrets, dispatch payloads, docs | `tests/test_*_contract.py`, source-string and YAML structure assertions |
| Adversarial/security | Challenge trust, identity, parsing, credentials, and output boundaries | replay, stale head, prompt-shaped text, ANSI/Unicode, malformed JSON, symlinks |
| Integration | Exercise scripts against realistic Git/GitHub-shaped fixtures | scheduler decisions, materializers, sandbox wrappers, artifact receipts |
| Concurrency/race | Prove expected-head and idempotency behavior | moved head/base, duplicate mention, overlapping writer, rerun attempt |
| Performance/resource | Bound attacker-influenced processing | large redaction input, deep JSON, output and file quotas |
| Compatibility | Preserve thin consumers and runtime versions | Python versions, shell syntax, Node action runtime, result/dispatch schemas |
| Operational acceptance | Demonstrate integrated behavior | protected-main central run and real product-repository canary |

## 3. Mandatory gate inventory

A source pull request normally requires:

- focused regression tests for the changed boundary;
- complete repository test suite;
- 100% production statement and branch coverage;
- 100% public docstring coverage;
- compile/syntax checks for supported languages and shells;
- secret scan, Semgrep, CodeQL, dependency/OSV, Scorecard, SBOM, and applicable Strix evidence;
- documentation contract and `git diff --check`;
- current-head automated review and zero valid unresolved findings; and
- qualifying independent non-author approval under live repository policy.

Skipped-required, neutral-required, absent, queued, cancelled, stale-head, or synthetic-only evidence is non-passing.

## 4. Revision and authority tests

Tests must cover:

- source head differs from synthetic merge SHA;
- PR snapshot base differs from current live base tip;
- head/base moves after evidence collection and before write;
- check success, status success, bot approval, comment prose, dismissed approval, author approval, and human current-head approval remain distinct;
- last-push approval invalidation and unresolved threads;
- expected-head branch update, comment resolution, auto-merge, and direct merge rejection; and
- protected-main acceptance uses the integrated commit, not the feature-branch head.

## 5. Sandbox and redaction test matrix

| Path | Success | Failure | Timeout | Setup/launch failure | Structured output |
|---|---:|---:|---:|---:|---:|
| `sandboxed_verify.py` stdout/stderr | Required | Required | Required | Required | Required |
| `sandboxed_web_e2e.py` E2E output | Required | Required | Required | Required | Required |
| Backend/frontend service logs | Required | Required | N/A | Required | Tail metadata |
| Command metadata | Required | Required | Required | Required | Result JSON |

Credential forms include assignments, JSON keys/values, Authorization/Cookie, private keys, JWT/provider tokens, URL userinfo, separated CLI arguments, `curl -u`, `sshpass`, MySQL/Docker password forms, nested `sh -c`/`env`, ANSI/backspace/cursor/default-ignorable splits, multiline and escaped forms, explicit allowed values, and cross-stream/result reassembly.

Preservation assertions include exact child argv and environment semantics, ordinary diagnostic text, stdout/stderr distinction, exit code, cleanup/keep-sandbox behavior, stable result keys, valid one-line JSON, and bounded near-linear processing. Unsafe preflight/setup paths must return the documented code without output that can collide with a secret.

Redaction tests do not claim resource safety. Separate fixtures must bound total captured output, in-memory processing, and service-log file size.

## 6. Retry and incident tests

For each retrying operation, tests include one accepted transient class, exhaustion, backoff/attempt count, success after transient failure, and immediate rejection of integrity, authorization, TLS, ref, schema, and product/test failures. A retry must not erase the first failing boundary or replace failure with a success-shaped skip.

Incident tests verify symptom-to-root-cause distinction, rollback behavior, reopen criteria, and protected-main/consumer proof.

## 7. Documentation-as-code tests

The current documentation gate verifies structural contracts:

- every required document and ADR exists and is indexed;
- internal index links resolve;
- Mermaid fences are balanced and critical exact-head transitions are present;
- required workflow/script names referenced by architecture exist;
- data-model entities use two-or-more-word `snake_case` names and retain the
  selected many-observations-to-one-revision relationships;
- the value-free registry exactly covers literal workflow secret names and the
  prohibition on `COPILOT_GITHUB_TOKEN` is present; this registry does not
  prove reusable `workflow_call.secrets` declarations or caller mapping;
- traceability contains every PRD/TRD identifier, locator/accountability
  columns, and a controlled maturity value; repository-path resolution is
  checked separately from semantic implementation proof; and
- no timeless architecture depends on an unstable literal head SHA or run ID.

These tests do not prove Mermaid rendering, every ERD semantic, reusable-secret
mapping, traceability-row semantics, live GitHub truth, standards correctness,
or that a named operational receipt currently exists. Rendering/review, live API/ruleset inspection, focused source tests, and
protected-main acceptance remain separate gates. The test name and PR summary
must not overstate a structural assertion as runtime proof.

## 8. Realistic consumer acceptance

After a central workflow repair merges:

1. select an affected low-risk product repository;
2. run the real thin consumer at a known exact source head;
3. prove the central trusted workflow revision and expected inputs/secrets;
4. exercise a positive scenario and the relevant negative control;
5. verify GitHub check/review/status identity and diagnostic usefulness;
6. rehearse or execute rollback; and
7. record an `operational_acceptance` receipt in traceability.

Source-branch unit success alone cannot close a fleet incident.

## 9. Test evidence hygiene

Fixtures use synthetic credentials and non-personal data. Logs and artifacts are bounded and short-lived. Test secrets must still be redacted because scanners and humans cannot reliably distinguish a fixture from a live capability by appearance alone.
