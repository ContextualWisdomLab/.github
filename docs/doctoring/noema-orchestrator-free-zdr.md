# Doctoring record: Required reviews through the vendored orchestrator sidecar

- **Date:** 2026-08-28
- **Subject:** Required Noema, OpenCode dispatch, and Strix reviews no longer
  select direct provider model routes. They use the same vendored
  `contextual-orchestrator` sidecar (`orchestrator/free`, ZDR-first
  auto-discovery).
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
only `127.0.0.1` / `::1` when that origin matches the exact configured
`CONTEXTUAL_ORCHESTRATOR_BASE_URL` origin. The `NOEMA_LLM_VIA_ORCHESTRATOR`
marker is metadata only and never widens the allowlist.

Noema reviewer identity is unchanged: `NOEMA_REVIEW_TOKEN` / GitHub App /
OIDC. Review mutation is still not `github.token`. Required OpenCode and Strix
use the same gateway model and do not add direct-provider fallback paths. The
hourly-review-repair roster is untouched.

## Verification contract

`tests/test_contextual_orchestrator_review_sidecar_contract.py` and
`tests/test_required_workflow_queue_contract.py` assert the workflow provisions
the sidecar, the five secrets, and `orchestrator/free`, and no longer mentions
the NIM hardcode. `tests/test_noema_review_gate.py` covers the sidecar
allowlist and keeps localhost / non-sidecar private IP rejection. The required
OpenCode/Strix workflow contracts cover the gateway-only model, exact ZDR
visibility wiring, gateway token diagnosis, and the empty external fallback.

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

## Private/internal repository routing

Noema resolves target visibility with its repository-scoped reviewer token.
Private/internal targets require an attested ZDR-only `orchestrator/free`
catalog. Missing visibility, malformed policy input, or an empty ZDR pool fails
the required review; it never falls back to a non-ZDR provider.
