# Strix contextual-orchestrator gateway doctoring

## Failure evidence

The triggering consumer scan produced no vulnerability artifact. Its terminal
log recorded provider infrastructure failures across NVIDIA NIM, OpenRouter, and
direct OpenAI, followed by the existing fail-closed
`STRIX_PROVIDER_UNAVAILABLE` classification. Repository Test, Release, SAST, and
Security workflows were independently successful on the same consumer head.

## Causal boundary

The defect is not in the consumer product tree. It is the duplicated routing
authority in central Strix: the scanner selected and retried direct providers even
though the organization already had a pinned contextual-orchestrator gateway with
model discovery, ZDR policy, and provider-family diversity.

## Corrective control

```text
five provider credentials
→ process-local contextual-orchestrator KV
→ live discovery + ZDR-first zero-cost catalog
→ authenticated 127.0.0.1 OpenAI-compatible API
→ Strix openai/orchestrator/free
→ authoritative report or fail-closed required check
```

Direct providers are retained only for an explicit diagnostic override. The
normal gateway route has no scanner-owned fallback list.

## Security and operability

- The sidecar is pinned by commit SHA.
- Provider credentials never become Strix key files in gateway mode.
- The bearer token is generated per job, rejects line breaks, and is masked.
- The base URL must be exact IPv4 loopback with a valid port.
- Sidecar packages use an isolated target directory rather than the scanner's
  hash-locked environment.
- Health failure, empty discovery, missing credentials, and provider exhaustion
  remain non-passing.
- Consumer PRs are rechecked on unchanged exact heads after the central fix.

## Traceability

- ADR: `docs/adr/0004-strix-contextual-orchestrator-authority.md`
- Workflow: `.github/workflows/strix.yml`
- Sidecar: `scripts/ci/contextual_orchestrator_review_sidecar.sh`
- Required smoke: `scripts/ci/strix_required_workflow_smoke.sh`
- Contract: `tests/test_strix_contextual_orchestrator_contract.py`
- Predecessor gateway ADR: `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
