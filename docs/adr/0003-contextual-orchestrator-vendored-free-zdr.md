# ADR-0003: Vendored contextual-orchestrator review sidecar with governed free pool

- Status: Accepted; consolidated 2026-09-01
- Date: 2026-08-27
- Scope: central OpenCode, Noema, and Strix review pipelines
- Ownership: `ContextualWisdomLab/.github` owns CI/control-plane wiring; `ContextualWisdomLab/contextual-orchestrator` owns provider discovery, candidate admission, routing, and inference.

## Current decision

Every central review model call goes through the vendored `ContextualWisdomLab/contextual-orchestrator` sidecar. OpenCode, Noema, and Strix use the virtual model `orchestrator/free`; private/internal targets additionally require ZDR and fail closed when no eligible ZDR route exists. The current reviewed sidecar source is pinned exactly to contextual-orchestrator commit `8cd99f139915131ba0239bce12a5d6a5fd85394e`; changing that supply-chain identity requires ordinary exact-head review and verification rather than an inferred compatible version.

All five GitHub Secrets may be supplied to global contextual-orchestrator discovery: `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, and `OPENAI_API_KEY`. Credential discovery and free-pool candidate admission are separate contracts. `OPENAI_API_KEY` may be registered and may globally discover OpenAI models, but any row sourced through `OPENAI_API_KEY` is excluded from `orchestrator/free` candidate generation, preflight, routing, failover, fallback, serving, and durable free-pool persistence. The eligible provider-account sources for `orchestrator/free` are `BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, and `OPENROUTER_API_KEY`, subject to the remaining explicit free/privacy/capability evidence predicates.

`scripts/ci/contextual_orchestrator_review_policy.py` is an admission boundary, not a router. Every row that satisfies the explicit pool, credential-source, zero-cost, capability, and when required ZDR predicates remains admitted with neutral priority. Serialization order is provenance only. The policy MUST NOT use candidate-count caps, per-account quotas, provider-family quotas, provider/model/cost sorting, hand-authored priorities, arbitrary fallback ratios, model-name inference, or any other heuristic to change candidate membership or preference. Legacy `limit` and `account_cap` parameters may remain temporarily as ignored compatibility inputs, but their values are non-authoritative.

The historical twelve-route total catalog cap, eight-route primary cap, per-account cap, `priority=-rank`, cost/provider ordering, and Strix `orchestrator/auto` paid-fallback design are superseded. Incident evidence that motivated those controls remains useful for observability and research, but an incident-derived rule is not a valid decision policy without an explicit mathematical/statistical/psychometric model, authoritative standard, experimentally validated evidence, or documented research-backed algorithm with executable provenance.

No heuristic, rule of thumb, hand-tuned threshold, arbitrary weight, ad-hoc score, undocumented tie break, name-based inference, or magic-number decision rule may determine routing, model selection, test-time-compute allocation, response-quality scoring, RAG evaluation, weighting, thresholding, admission, fallback order, or prioritization. If the required evidence is unavailable, the system fails closed or records unresolved evidence; it does not invent a substitute heuristic.

Model inference has no repository- or application-configured fixed wall-clock cutoff. OpenCode, Noema, Strix, and the contextual-orchestrator sidecar **MUST NOT impose a fixed wall-clock timeout on model inference**, including initial completion ping, warm-up, retry, repair verdicts, or substantive review calls. A slow reasoning model is not classified as unavailable merely because it runs for minutes or hours. Explicit operator cancellation, exact-head supersession, and an external runner/platform termination remain observable lifecycle events; an externally interrupted run is incomplete evidence and cannot become an approval or availability judgment. The same principle applies to bootstrap discovery/readiness paths when a fixed local deadline would silently convert an otherwise usable provider into a negative routing signal.

Reference-free/model-response quality evaluation uses the `ContextualWisdomLab/fast-mlsirm` psychometric/statistical boundary where applicable. The GitHub policy layer does not synthesize a model-quality scalar.

The sidecar retains secret-free discovery, admission, and runtime-preflight evidence. Raw credentials, prompts, and unredacted provider error bodies are never persisted in ordinary evidence. Exact-head GitHub Checks and current review findings remain authoritative for merge.

## Verification contract

Executable tests must prove at least that:

1. all five credentials may be supplied and globally discovered;
2. the four free-eligible credential sources are considered independently;
3. OpenAI may be globally discovered while contributing zero `orchestrator/free` candidates;
4. OpenAI-derived rows cannot enter free-pool preflight, fallback, failover, serving, or durable persistence;
5. more than the historical catalog cap can remain admitted without truncation or launcher failure;
6. legacy cap arguments cannot alter admission, ordering, or priority;
7. private targets cannot bypass ZDR admission;
8. logs and artifacts contain no secret values;
9. the accepted ADR names the exact vendored sidecar commit and forbids fixed wall-clock inference timeouts.

## References

Chen, L., Zaharia, M., & Zou, J. (2024). FrugalGPT: How to use large language models while reducing cost and improving performance. *Transactions on Machine Learning Research*. https://arxiv.org/abs/2305.05176

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E., Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with preference data* [Preprint]. arXiv. https://arxiv.org/abs/2406.18665

Xu, J., Sun, Q., Schwendeman, P., Nielsen, S., Cetin, E., & Tang, Y. (2026). *TRINITY: An evolved LLM coordinator* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2512.04695

OpenRouter. (2026). *Zero data retention*. https://openrouter.ai/docs/guides/features/zdr

OpenRouter. (2026). *Provider logging: Data retention & logging*. https://openrouter.ai/docs/guides/privacy/provider-logging
