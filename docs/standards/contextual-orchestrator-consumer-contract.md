# Contextual Orchestrator Consumer Contract

- Status: Normative
- Effective date: 2026-08-16
- Applies to: every ContextualWisdomLab production component that calls `ContextualWisdomLab/contextual-orchestrator`

## Required default

Ordinary production requests MUST delegate execution topology to contextual-orchestrator by selecting adaptive `auto` mode.

The shared routing objective is lexicographic:

1. satisfy or maximize task-specific capability, quality, and safety evidence;
2. allocate additional test-time compute, decomposition, verification, or synthesis when the task requires it;
3. among quality-sufficient candidates, minimize trustworthy known execution cost;
4. classify absent, malformed, negative, NaN, or infinite price metadata as unpriced, never free.

A cheaper lower-capability route MUST NOT displace a stronger route merely because of price. A simple task MAY still use one model when the adaptive policy determines that one call is quality-sufficient.

## Consumer boundary

A consumer owns:

- its domain prompt and untrusted-input separation;
- authorization, tenant, purpose, and egress policy;
- bounded request and response sizes;
- strict output parsing and domain validation;
- deterministic or human-reviewed fallback;
- provenance, usage, and returned orchestration evidence when available.

The consumer MUST NOT independently choose the ordinary production model graph, provider, workflow depth, verifier count, recursion depth, or cost tie-break.

## Structured output and tools

Provider-native `response_format`, tool calls, and Responses API envelopes may force contextual-orchestrator onto a one-worker passthrough because those complete provider envelopes cannot be merged losslessly.

Therefore an ordinary adaptive consumer MUST NOT send such a passthrough trigger unless the product explicitly requires the original provider envelope. When strict JSON is needed, the adaptive path SHOULD:

1. instruct the orchestrated workflow to return one bounded JSON value;
2. omit provider-native structured-output passthrough;
3. validate the assistant text locally against an exact schema;
4. fail closed when validation fails.

A direct-provider compatibility path MAY retain native structured output. Orchestration-only fields MUST be sent only to contextual-orchestrator, not blindly to generic OpenAI-compatible providers.

## Allowed explicit modes

Explicit fixed modes are exceptions, not defaults. They are permitted for:

- controlled route/verify/conduct ablation;
- a deliberately checked judgment contract such as worker-plus-verifier adjudication;
- a live conformance or benchmark harness;
- bounded incident response or operator override documented in an ADR.

Every exception MUST be named, tested, and documented so it cannot silently become the general product default.

## Required regression evidence

Each consumer repository MUST test the exact outbound request body or injected client call. At minimum, the test must prove:

- ordinary contextual-orchestrator traffic selects `auto`;
- generic providers receive no orchestration-only field;
- an adaptive structured-output path does not accidentally activate single-worker passthrough;
- malformed orchestrated output fails closed;
- explicit specialized modes remain explicit and isolated.

The central runtime MUST expose its routing objective and unpriced-model policy in an operator-readable policy snapshot or equivalent audit evidence.

## Research boundary

TRINITY is evidence that a lightweight coordinator can adaptively delegate
multiple turns across specialized Thinker, Worker, and Verifier roles. This
contract adopts the observable boundary—adaptive delegation, bounded budgets,
and auditable routing evidence—not TRINITY's learned coordinator, evolutionary
optimizer, or model pool. Those remain implementation choices for the central
runtime and require their own benchmark and rollback evidence.

## Current adoption program

The 2026-08-16 migration program covers the central runtime and known consumers including fast-mlsirm, DiagramWeave, LineageWeave, LifeOS, ScopeWeave, Wardnet, pg-erd-cloud, naruon, and four-pillars. Repositories with no production call are not modified merely because they mention contextual-orchestrator in documentation.

## References

Omidvar, H., & Akhlaghi, V. (2026). *A communication-theoretic framework for LLM agents: Cost-aware adaptive reliability* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2605.09121

Tang, Y., Cetin, E., Xu, J., Sun, Q., Nielsen, S., Richard, V., Goda, H., Tymchenko, I., Nguyen, N., Lee, H., Ashiga, M., Kotyan, S., Kuroki, S., & Clanuwat, T. (2026). *Sakana Fugu technical report* [Technical report]. arXiv. https://doi.org/10.48550/arXiv.2606.21228

Zhang, S., Yu, Y., Li, Y., Zhao, W., Yang, Y., Zhang, Y., & Liu, T. (2025). *Conductor: Learning to route multi-agent workflows* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04388

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026). *TRINITY: An evolved LLM coordinator* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04695
