# ADR-0004: contextual-orchestrator owns normal Strix provider routing

- Status: Proposed
- Date: 2026-08-28
- Owners: ContextualWisdomLab central CI maintainers
- Figma File ID: N/A (workflow/control-plane change; no customer UI)

## Context

Required Strix scans were serialized per repository, but each scan still owned a
hard-coded direct provider chain. A live DiskSage exact-head scan exhausted four
independent paths in one run: NVIDIA rate limiting, an unavailable NVIDIA model,
an OpenRouter upstream error, and exhausted direct OpenAI credit. No authoritative
vulnerability report existed, so the required check correctly failed closed, but
consumer product PRs could not repair the shared authority boundary.

The central repository already vendors a pinned contextual-orchestrator sidecar.
It registers the five organization provider credentials in a process-local KV,
performs live discovery, applies the reviewed zero-cost/ZDR policy, and exposes
`orchestrator/free` through an authenticated OpenAI-compatible loopback API.

## Decision

Normal Strix scans SHALL provision that sidecar and call
`openai/orchestrator/free` through exact IPv4 loopback. The sidecar owns
provider/model discovery and fallback. Strix SHALL NOT add a second direct
fallback chain for the gateway-backed route.

A caller MAY use `repository_dispatch.strix_llm` to select an existing direct
provider model for bounded diagnosis. That override is explicit, auditable, and
does not change the normal default.

The sidecar dependency tree SHALL be installed from the exact vendored commit's
hash lock, with binary-only distributions, into an isolated `--target` directory
so it cannot rewrite the hash-locked Strix runtime. Its generated
bearer token SHALL be line-safe, masked before export, and passed to Strix only
through a mode-specific file. Missing credentials, unhealthy startup, non-loopback
base URLs, invalid ports, and missing tokens fail closed.

## Consequences

- Shared provider outages are handled by one routing authority instead of nested
  retry/fallback loops.
- Provider credentials remain inside the gateway process; the scanner sees only
  a short-lived loopback credential.
- A gateway outage remains non-passing security evidence.
- Existing direct-provider diagnostic contracts and their tests remain supported.
- After merge, consumer PRs require a fresh exact-head Strix run; predecessor
  outage evidence is not transferred.

## Verification

- RED/GREEN static contract for the workflow, model namespace, loopback and token.
- Bounded required-workflow smoke contract.
- Bash syntax and YAML parse.
- Existing full organization Checks, independent review, and protected merge.

## Rollback

Revert this ADR and its workflow commit. Do not partially restore a direct default
while leaving gateway key/base files active. Re-run the complete required Strix
contract and affected consumer exact heads after rollback.
