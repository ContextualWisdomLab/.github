# Doctoring record: Noema review through the vendored orchestrator sidecar

- **Date:** 2026-08-27
- **Subject:** Required Noema review no longer pins a public-repo NVIDIA NIM
  endpoint. It uses the same vendored `contextual-orchestrator` sidecar as the
  autofix writer (`orchestrator/free`, ZDR-first auto-discovery).
- **Decision record:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](../adr/0003-contextual-orchestrator-vendored-free-zdr.md)
- **Related:** [`docs/doctoring/contextual-orchestrator-vendored-sidecar.md`](contextual-orchestrator-vendored-sidecar.md)

## What changed

`.github/workflows/noema-review.yml` provisions
`scripts/ci/contextual_orchestrator_review_sidecar.sh` with the five provider
secrets (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
`OPENROUTER_API_KEY`, `OPENAI_API_KEY`) and points `NOEMA_LLM_API_URL` at the
sidecar loopback chat-completions URL, `NOEMA_LLM_MODEL` at
`orchestrator/free`, and `NOEMA_LLM_API_KEY` at the process-local sidecar
bearer. The public-repo `integrate.api.nvidia.com` /
`nvidia/nemotron-3-ultra-550b-a55b` hardcode is deleted. There is no sequential
OpenAI or Azure fallback hop.

`scripts/ci/noema_review_gate.py` `call_llm` still rejects `localhost` and
arbitrary private, link-local, multicast, and unspecified targets. It allows
only `127.0.0.1` / `::1` when that origin matches
`CONTEXTUAL_ORCHESTRATOR_BASE_URL` or `NOEMA_LLM_VIA_ORCHESTRATOR` is an
explicit truthy flag.

Noema reviewer identity is unchanged: `NOEMA_REVIEW_TOKEN` / GitHub App /
OIDC. Review mutation is still not `github.token`. `strix.yml` and the
hourly-review-repair roster are untouched.

## Verification contract

`tests/test_contextual_orchestrator_review_sidecar_contract.py` and
`tests/test_required_workflow_queue_contract.py` assert the workflow provisions
the sidecar, the five secrets, and `orchestrator/free`, and no longer mentions
the NIM hardcode. `tests/test_noema_review_gate.py` covers the sidecar
allowlist and keeps localhost / non-sidecar private IP rejection.

## Rollback

Restore the previous Noema LLM env (`vars.NOEMA_LLM_API_URL` /
`secrets.NOEMA_LLM_API_KEY`) only if the sidecar cannot be provisioned. Do not
reintroduce a public-repo direct-provider pin. Do not weaken `call_llm` to
"any localhost".

## References (APA 7th)

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved
August 27, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

OpenRouter. (2026, August). *Zero data retention* [Documentation].
https://openrouter.ai/docs/guides/features/zdr

ContextualWisdomLab/.github. (2026, August 27).
*ADR-0003: Vendored contextual-orchestrator review sidecar with the ZDR-first
orchestrator/free pool*.
