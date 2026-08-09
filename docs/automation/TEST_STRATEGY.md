# Automation control-plane test strategy

Status: active_pr

## Test layers

1. Static contracts validate immutable pins, explicit secret interfaces, workflow provenance, required paths, status vocabulary, and forbidden stale literals.
2. Unit/property tests cover normalization, evidence classification, exact-head/live-base identity, retry classes, queue lanes, writer leases, and output redaction.
3. Integration tests exercise workflow event envelopes, OIDC/App claims, artifact handoff, concurrency isolation, and negative controls.
4. Exact-head GitHub evidence proves the unchanged PR head passed required product/security/dependency checks.
5. Protected-main acceptance exercises scheduled/manual real consumers after integration.

## Permanent negative cases

Tests must reject stale heads, synthetic merge evidence, skipped-required checks, status-only approval, author approval, spoofed reviewer identity, prompt-injected shell fragments, untrusted redirects, ref/auth/TLS retry, arbitrary output paths, secret-shaped stdout/stderr/service tails, and PR self-enablement of privileged policy.

## Documentation fitness

`tests/test_automation_documentation.py` verifies required documents and indexes, controlled implementation status, Mermaid fence integrity, absence of ephemeral full SHAs in timeless documents, detailed ADR coverage, and traceability to live workflow paths. `.github/workflows/automation-documentation-quality-ci.yml` runs the contract on the exact source revision.

## Acceptance evidence

A green run is valid only for the commit actually checked out. Pending, cancelled, rate-limited, stale, predecessor, synthetic-merge, skipped-required, absent, or infrastructure-only results are not success. Operational repairs additionally require a protected-main consumer run and a negative control.

## Coverage and docstrings

Owned production code targets 100% statement and branch coverage and public callable docstrings. Test-only documentation contracts are deterministic and dependency-free so they can run before model credentials or network access.
