# Automation control-plane test strategy

Status: active_pr

## Test layers

1. Static contracts validate immutable pins, explicit secret interfaces, workflow provenance, required paths, status vocabulary, external-orchestrator/GitHub authority separation, canonical documentation ownership, and forbidden stale literals.
2. Unit/property tests cover normalization, evidence classification, exact-head/live-base identity, retry classes, queue lanes, writer leases, defer identities, continuation handoffs, double-exit semantics, and output redaction.
3. Integration tests exercise workflow event envelopes, OIDC/App claims, artifact handoff, concurrency isolation, negative controls, and lane rotation when one exact PR/action is blocked.
4. Exact-head GitHub evidence proves the unchanged PR head passed required product/security/dependency checks.
5. Protected-main acceptance exercises scheduled/manual real consumers after integration.
6. External automation acceptance verifies that a prompt/control update or status event returns through queue selection rather than terminating while a separate safe lane remains.

## Permanent negative cases

Tests must reject stale heads, synthetic merge evidence, skipped-required checks, status-only approval, author approval, spoofed reviewer identity, prompt-injected shell fragments, untrusted redirects, ref/auth/TLS retry, arbitrary output paths, secret-shaped stdout/stderr/service tails, PR self-enablement of privileged policy, and conversation/prompt text presented as protected-main implementation.

The continuation contract additionally treats these as failures:

- terminating after a prompt update while a safe GitHub lane is executable;
- terminating after a documentation audit/update while another safe lane is executable;
- terminating after one merge, review request, RCA, or defer decision without queue reselection;
- treating a user-visible status response as an exit condition;
- performing only one exit sweep when it discovers work; and
- creating a competing documentation authority when a canonical line already owns the scope.

## Documentation fitness

`tests/test_automation_documentation.py` verifies required documents and indexes, controlled implementation status, Mermaid fence integrity, absence of ephemeral full SHAs in timeless documents, detailed ADR coverage through ADR-0010, the documentation-fitness audit, continuation/reconciliation invariants in core documents, and traceability to live workflow paths. `.github/workflows/automation-documentation-quality-ci.yml` runs the contract on the exact source revision.

Documentation tests are intentionally dependency-free and should fail before implementation/documentation repair when a new canonical artifact or invariant is introduced. A documentation file being present is necessary but not sufficient; the controlled maturity state prevents active or planned behavior from being mistaken for protected-main implementation.

## Acceptance evidence

A green run is valid only for the commit actually checked out. Pending, cancelled, rate-limited, stale, predecessor, synthetic-merge, skipped-required, absent, or infrastructure-only results are not success. Operational repairs additionally require a protected-main consumer run and a negative control.

For premature-termination repairs, acceptance also requires runtime evidence that an exact blocked lane is deferred and a different safe lane is selected before termination. A prompt/configuration diff alone is not operational closure.

## Coverage and docstrings

Owned production code targets 100% statement and branch coverage and public callable docstrings. Test-only documentation contracts are deterministic and dependency-free so they can run before model credentials or network access.
