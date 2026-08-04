# Doctoring record: shared free-first LLM fallback policy

## Clinical finding

The central review workflows had three different model-selection contracts.
OpenCode Agent already had a broad pool and retries, Strix had provider-specific
fallbacks, and Noema made one model call. Their credentials, result schemas,
review identities, and security gates were intentionally different, but model
cost ordering was not governed by one auditable policy. This created four
risks: paid inference could run before an available free candidate, free-to-free
fallback was inconsistent, repository-visibility constraints could drift, and
provider pricing changes had no single review surface.

## Intervention

A pure policy module was added to `contextual-orchestrator` and imported into
the central `.github` repository through an exact-commit vendoring receipt. It
performs no network I/O. It validates trusted candidate metadata and returns a
deterministic eligible sequence in which all free candidates precede all paid
candidates. Thin adapters hand that sequence to the existing Noema, OpenCode,
and Strix execution engines.

The transport boundary is deliberate. Combining the agents into one HTTP
client would also combine privileges and could weaken current-head validation,
reviewer authentication, report parsing, or provider-specific credential
handling. The shared module therefore owns only candidate validation and
ordering; each agent retains its existing acceptance and security contract.

## Evidence-based rationale

LLM cascade research demonstrates that lower-cost models can be attempted
before escalation, but also shows that useful routing depends on task-specific
quality estimation. FrugalGPT reports large cost reductions from cascades;
RouteLLM learns cost-quality routing from preference data; and cascade-routing
research formalizes when routing and cascading can be combined. The present
implementation is intentionally the deterministic baseline: it enforces an
operator-selected budget boundary but does not claim to predict review quality.
A learned router may be added only after it is calibrated on the exact code
review and security tasks and preserves the selected free-before-paid policy.

Current provider documentation also shows that “free” is contractual and
mutable. GitHub Models includes rate-limited free usage, but an organization can
opt into paid usage. OpenRouter free variants and the `openrouter/free` router
have changing availability and lower rate limits. NVIDIA describes hosted API
access as a free development/prototyping endpoint that may be throttled. The
manifest therefore requires explicit `cost_tier` metadata and never infers cost
from a model name.

## Safety and privacy controls

- Public hosted candidates are ineligible for private and internal repositories.
- Noema's existing reviewer token hierarchy is unchanged.
- OpenCode's provider keys remain scoped to the privileged review job and its
  unchanged core continues to reject synthetic approval after exhaustion.
- Strix's existing per-model key/API-base selection and severity gate remain
  authoritative.
- Secret values are not persisted in the manifest, plan, receipt, diagnostics,
  or test evidence.
- Vendor files are verified as regular non-symlink files against exact Git blob
  identities before import.
- The manifest and receipt reject duplicate JSON keys, unknown fields, unsafe
  identifiers, duplicate logical targets, unsupported schema versions, and
  empty eligible pools.
- Provider exceptions are summarized by type/status rather than response body,
  reducing accidental prompt or credential disclosure.

## Verification record

The implementation-specific test suite contains 74 regression tests covering:

- committed manifest plus exact vendored module integration for all three agents;
- free-before-paid and free-to-free ordering;
- stable priority and declaration-order ties;
- repository visibility, capability, and credential-name filtering;
- configured-pool drift and duplicate rejection;
- vendor receipt, source commit, file map, symlink, and Git blob verification;
- bounded UTF-8 JSON, duplicate-key, and import-path hardening;
- Noema fallback, environment restoration, secret-free failure diagnostics,
  and preservation of the original single-model core;
- OpenCode adapter delegation and no-model behavior;
- Strix public NIM, GitHub Models, configured-primary, and fail-closed adapter
  behavior.

Local exact-slice results before PR creation:

- 74 tests passed;
- `contextual_fallback_policy.py`: 174 statements, 56 branches, 100%;
- central Python policy surface: 487 statements, 180 branches, 100%;
- Noema wrapper: 93 statements, 36 branches, 100%;
- contextual-orchestrator policy source: 270 statements, 94 branches, 100%;
- all newly public Python symbols have docstrings;
- Bash syntax checks passed for the OpenCode adapter and Strix model utility.

Repository-wide GitHub checks on the exact PR head remain the authoritative
merge gate because they also execute the pre-existing Noema, OpenCode, Strix,
SAST, supply-chain, and required-workflow contracts.

## APA 7 references

Chen, L., Zaharia, M., & Zou, J. (2023). *FrugalGPT: How to use large language
models while reducing cost and improving performance* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2305.05176

Dekoninck, J., Baader, M., & Vechev, M. (2024). *A unified approach to routing
and cascading for LLMs* [Preprint]. arXiv.
https://doi.org/10.48550/arXiv.2410.10347

GitHub. (n.d.). *GitHub Models billing*. Retrieved August 5, 2026, from
https://docs.github.com/en/billing/concepts/product-billing/github-models

NVIDIA. (n.d.). *Get started with NVIDIA NIM for LLMs*. Retrieved August 5,
2026, from
https://docs.nvidia.com/nim/large-language-models/1.10.0/getting-started.html

NVIDIA. (n.d.). *NVIDIA NIM model API: Free endpoint and API trial terms*.
Retrieved August 5, 2026, from https://build.nvidia.com/

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes*
(RFC 6585). RFC Editor. https://doi.org/10.17487/RFC6585

Ong, I., Almahairi, A., Wu, V., Chiang, W.-L., Wu, T., Gonzalez, J. E.,
Kadous, M. W., & Stoica, I. (2024). *RouteLLM: Learning to route LLMs with
preference data* [Preprint]. arXiv. https://doi.org/10.48550/arXiv.2406.18665

OpenRouter. (n.d.-a). *Free models router*. Retrieved August 5, 2026, from
https://openrouter.ai/docs/guides/routing/routers/free-router

OpenRouter. (n.d.-b). *Free variant*. Retrieved August 5, 2026, from
https://openrouter.ai/docs/guides/routing/model-variants/free

OpenRouter. (n.d.-c). *Model fallbacks*. Retrieved August 5, 2026, from
https://openrouter.ai/docs/guides/routing/model-fallbacks

Rescorla, E., Nottingham, M., & Bishop, M. (2022). *HTTP semantics* (RFC 9110).
RFC Editor. https://doi.org/10.17487/RFC9110
