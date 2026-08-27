# Doctoring record: contextual-orchestrator vendored review sidecar (ZDR-first `orchestrator/free`)

- **Date:** 2026-08-27
- **Subject:** Central CI review no longer pins direct provider endpoints; it
  routes through a vendored `contextual-orchestrator` gateway sidecar under the
  fail-closed zero-cost pool `orchestrator/free`, with ZDR-compliant routes
  prioritized.
- **Decision record:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](adr/0003-contextual-orchestrator-vendored-free-zdr.md)

## What changed

`pr-review-autofix.yml` now provisions the sidecar
(`scripts/ci/contextual_orchestrator_review_sidecar.sh`) before its OpenCode
runs, seeds the five provider secrets (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
`NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) into the
process-local KV, runs auto model discovery over them, and serves the
ZDR-prioritized free catalog at loopback. Both the ordinary autofix and the
conflict-repair agent run `--model contextual-orchestrator/orchestrator/free`.
The shared `opencode.jsonc` default route changes identically.

`NVIDIA_NIM_API_KEY_SUB` and `BYTEZ_API_KEY` have no other workflow reference in
this repository; the gateway KV is their only consumer, matching the
orchestrator's `review_gateway.REVIEW_CREDENTIAL_NAMES`.

## Why this is still the same trust boundary

- The OpenCode subprocess still runs with `GITHUB_TOKEN` / `GH_TOKEN` /
  `ACTIONS_ID_TOKEN_REQUEST_*` stripped (the exact-credential sanitization is
  unchanged and asserted by contract tests).
- Mutation still requires `PR_REVIEW_MERGE_TOKEN` /
  `OPENCODE_APPROVE_TOKEN` / the exchanged OpenCode app token; `github.token`
  remains read-only.
- The gateway binds to loopback only; it never leaves the runner. Secrets are
  bootstrap transport into the KV and are never read back from environment at
  request time.

## ZDR definition and evidence

ZDR here follows OpenRouter's definition — "a provider will not store your
data for any period of time", and zero retention implies no training. The
policy is conservative: an un-ascertained provider is treated as retaining and
training (OpenRouter's own stance). Evidence sources:

1. OpenRouter ZDR endpoint feed `https://openrouter.ai/api/v1/endpoints/zdr`
   (auto-updated, machine-readable) — authoritative when egress allows it;
2. the dated static attestation table in `scripts/ci/zdr_policy.py`
   (OpenRouter scope attested; NVIDIA NIM primary/sub, OpenAI, and Bytez
   direct scopes are not attested as zero-retention and are therefore
   non-ZDR by default).

## Audit trail

- `scripts/ci/zdr_policy.py` — org ZDR provider policy (offline-tested).
- `scripts/ci/contextual_orchestrator_review_policy.py` — discovery report →
  ZDR-prioritized free agents catalog + audit report (offline-tested).
- `scripts/ci/contextual_orchestrator_review_launcher.py` — same-process KV
  registration + discovery + serve (runs in the vendored runtime only).
- `scripts/ci/contextual_orchestrator_review_sidecar.sh` — pinned-SHA vendoring +
  health gate + GITHUB_ENV export.
- `tests/test_zdr_policy.py`,
  `tests/test_contextual_orchestrator_review_policy.py`,
  `tests/test_contextual_orchestrator_review_sidecar_contract.py`,
  `tests/test_pr_review_autofix_nvidia_nim_contract.py`,
  `tests/test_pr_review_autofix_writer_security_contract.py`.