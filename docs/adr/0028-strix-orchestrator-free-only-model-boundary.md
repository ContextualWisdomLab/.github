# ADR-0021: Strix model normalization is an `orchestrator/free` boundary

- Status: Proposed
- Date: 2026-09-02
- Owner: ContextualWisdomLab/.github central Strix review path

## Context

The protected central Strix workflow already provisions `ContextualWisdomLab/contextual-orchestrator`, requests the `orchestrator/free` virtual pool, supplies the five bootstrap credential sources, forces Zero Data Retention for private targets, and sets the workflow's external fallback list to empty. The shared `scripts/ci/strix_quick_gate.sh` nevertheless retained generic normalization for concrete provider model identifiers and historical direct-provider fallback code. That left a reusable execution boundary capable of accepting a provider/model name even though provider choice, free-pool admission, privacy admission, retry/failover, and serving are owned by contextual-orchestrator.

Under the organization no-heuristics and routing-owner contract, a GitHub Actions review path must not acquire a second provider/model router. The model identifier accepted by the Strix gate is therefore not a preference or fallback ranking input; it is an exact virtual-pool capability boundary.

## Decision

`normalize_model` in the Strix model helper accepts only `orchestrator/free` and its provider-qualified spelling `contextual-orchestrator/orchestrator/free`. All provider names, concrete model names, unqualified model names, and historical direct-OpenAI aliases fail closed before provider credentials or provider endpoints can become execution authority.

The five bootstrap secrets remain transport/discovery inputs to contextual-orchestrator. In particular, `OPENAI_API_KEY` is not removed from bootstrap or global discovery. The separate contextual-orchestrator free-pool admission contract decides which discovered credential sources may become `orchestrator/free` candidates; OpenAI-derived models remain excluded there while OpenAI integration may remain available to independently governed non-free/global pools.

For private targets, the central workflow's existing `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR=true` path remains mandatory. This ADR does not weaken or duplicate that policy; it prevents the Strix model selector from bypassing it with a concrete provider route.

## Executable evidence

`tests/test_strix_orchestrator_free_only.py` exercises the production shell helper. It admits the two exact governed virtual-model spellings and rejects direct OpenAI, OpenRouter, NVIDIA NIM, GitHub Models, Vertex/Gemini, and unqualified model identifiers before execution.

The full protected exact-head workflow set remains authoritative. Pending or queued runs are not passing evidence.

## Research and standards basis

This decision does not invent a quality score, routing rank, or threshold. It removes an overlapping router and delegates selection to the separately governed orchestrator. Privacy admission remains evidence-based and fail-closed.

OpenRouter. (2026). *Zero data retention*. https://openrouter.ai/docs/guides/features/zdr

ContextualWisdomLab. (2026, September 2). *ADR-0003: Vendored contextual-orchestrator review sidecar with governed gateway pools*. ContextualWisdomLab/.github.

## Consequences

- Strix cannot use a concrete provider/model identifier as an inference route.
- Provider discovery/failover stays inside contextual-orchestrator.
- `OPENAI_API_KEY` may still be registered and globally discovered; the free-pool candidate boundary, not secret transport, excludes OpenAI-derived candidates from `orchestrator/free`.
- Historical direct-provider fallback helpers become unreachable from the accepted Strix model boundary and should be removed as follow-up dead-code cleanup after exact-head regression evidence is available.
