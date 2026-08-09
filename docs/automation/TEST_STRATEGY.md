# Test strategy: CWL automation control plane

Status: normative verification and acceptance policy.

## Test objectives

Tests must prove that the control plane preserves exact identity, authority,
least privilege, fail-closed behavior, useful diagnostics, and protected-main
consumer operation under success, adversarial, failure, recovery, concurrency,
and rollback conditions. A passing happy path alone is insufficient.

## Coverage contract

- Every changed executable production statement and branch is exercised; new
  behavior has 100% owned line and branch coverage.
- Every changed public Python callable satisfies the repository docstring gate.
- Coverage thresholds cannot be lowered, exclusions broadened, or test files
  omitted to make a PR pass.
- Generated/vendor code and genuinely unreachable platform branches require a
  narrowly documented owner-reviewed exception rather than silent exclusion.
- Documentation-only changes have 100% coverage of their declared contract
  through `tests/test_automation_documentation_contract.py`, link resolution,
  Mermaid structure checks, and repository-native source checks.

Coverage is evidence for executed paths, not proof of correctness. Realistic
assertions, mutation-sensitive negative cases, and operational acceptance are
also required.

## Test layers

| Layer | Scope | Required evidence |
|---|---|---|
| Static contract | YAML, shell, Python, path/ref/input schemas, docs links, Mermaid fences | syntax/compile success and explicit contract assertions |
| Unit | parsers, classifiers, retries, evidence binding, redaction, authority decisions | deterministic boundary and error-path assertions |
| Property/fuzz | repository/ref/SHA, payload, output, status, archive, and token-shaped inputs | invariants hold across generated malformed/adversarial values |
| Component | workflow helper plus mocked GitHub/provider boundary | exact requests, permissions, idempotency, and bounded fallback |
| Integration | central workflow against representative repository fixtures | event-to-evidence behavior on exact source and live base |
| Concurrency | two workers, head movement, cancellation, lease loss | one writer, stale worker abort, no valid current evidence lost |
| Security | untrusted source/output, credential scope, replay, injection, redaction | fail-closed result with useful non-secret diagnostics |
| Recovery | transient outage, permanent failure, rollback, partial publication | classified retry/defer/reopen behavior and retained identity |
| Consumer acceptance | protected-main central workflow in an enrolled real repository | run/job, target, source head, live base, conclusion, recovery evidence |

## Required scenario matrix

Each decision or mutation path covers:

1. current exact head and current live base;
2. source head moves before and after materialization;
3. base moves after the PR snapshot;
4. missing, queued, cancelled, skipped, neutral, failed, predecessor, and
   synthetic evidence;
5. eligible, ineligible, self, bot, dismissed, stale, and change-request
   reviews;
6. transient API/provider failure versus permanent identity, integrity,
   authorization, TLS, and policy failure;
7. absent, narrowly scoped, expired, and over-broad credentials;
8. same-repository versus fork and cross-repository source refs;
9. normal, malicious, oversized, timeout, and credential-shaped output;
10. two competing workers plus a read-only fleet auditor;
11. rollback to the previous protected implementation;
12. real protected-main consumer success and failure.

## RED, GREEN, refactor

A behavioral fix starts with the smallest realistic failing test that
reproduces the defect. The test must fail for the intended reason. The narrowest
implementation makes it pass, after which the full affected matrix and full
repository suite run. Refactoring occurs only while those tests remain green.
Production code is not weakened to accommodate a mock that contradicts GitHub
or provider semantics.

## Evidence commands

The baseline documentation contract is runnable without third-party test
dependencies:

```bash
python3 -m unittest tests.test_automation_documentation_contract
```

The repository suite and owned coverage use the pinned project environment:

```bash
coverage run -m pytest tests
coverage report --show-missing
python3 -m compileall -q scripts tests
git diff --check
```

Repo-native shell contract tests and workflow-specific validators run when
their owned files change. Sandboxed product or web execution uses
`scripts/ci/sandboxed_verify.py` or `scripts/ci/sandboxed_web_e2e.py` and cites
the structured result marker.

## Merge and operational gates

A PR is not test-complete until the exact current head has all required tests,
security/provenance evidence, eligible review, and no valid unresolved finding.
A central operational repair is not incident-complete at merge: a protected-main
real-consumer run must exercise the changed boundary. Queue or provider waits
are deferred states and never converted into passing evidence.

## Test data and evidence hygiene

Fixtures use synthetic repositories, refs, actors, token shapes, and logs; real
secrets and customer content are prohibited. Failure output is bounded and
redacted at the publication boundary. Retained test evidence records the test
command, exact revision, environment contract, result, and relevant artifact or
run identity.
