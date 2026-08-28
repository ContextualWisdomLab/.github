# ADR-0003: Vendored contextual-orchestrator review sidecar with the ZDR-first `orchestrator/free` pool

- Status: accepted
- Date: 2026-08-27
- Scope: ContextualWisdomLab/.github central review pipelines (OpenCode autofix/dispatch + shared `opencode.jsonc` default + required Noema + Strix review)
- Decision: Route every central CI review write/model execution that touches contracts in this repository through the **vendored** `contextual-orchestrator` gateway, served as a per-runner sidecar, using the fail-closed zero-cost virtual model id `orchestrator/free`, with **Zero Data Retention (ZDR)-compliant routes prioritized** inside that pool.
- Ownership: `.github` owns control-plane evidence; `ContextualWisdomLab/contextual-orchestrator` owns the gateway. The 2026-08-18 org decision (recorded in `ContextualWisdomLab/contextual-orchestrator` AGENTS.md) already migrated OpenCode/Noema/Strix to the orchestrator backend; this ADR is the org-repo (provider-config) half of that decision.
- Figma File ID: N/A (no customer UI).

## Context

Central review paths previously pinned direct provider endpoints and hard-coded
model ids (e.g. `nvidia-nim/mistralai/mistral-small-4-119b-2603` in the PR
autofix writer). Provider keys were consumed from Actions env at the OpenCode
layer, and no path used the org's five-key auto-discovery. The orchestrator's
AGENTS.md (2026-08-18) commits the org to a shared gateway: register
`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
`OPENROUTER_API_KEY`, `OPENAI_API_KEY` into its KV, auto-discover models across
all five, and auto-optimize routing by cost.

## Decision

1. **Vendoring, pinned**: `scripts/ci/contextual_orchestrator_review_sidecar.sh`
   clones `ContextualWisdomLab/contextual-orchestrator` at an exact SHA
   (`984fe91c8f790d6367814dce13d63379bdf909c1` today) into `RUNNER_TEMP`. The
   source's `requirements.lock` is installed with `--require-hashes` and
   `--no-deps`, so dependency resolution cannot silently move the reviewed
   runtime.
   runtime entry (`contextual_orchestrator_review_launcher.py`) registers the
   five provider secrets plus the gateway bearer token into the process-local
   KV in the **same process** that performs model discovery and serves
   `/v1/chat/completions` and `/v1/responses` on loopback. Env is bootstrap
   transport only; request-time credential reads go through the KV.
2. **Auto model discovery + `orchestrator/free`**: discovery runs with the
   orchestrator's own `discover_all_models()` against the KV credentials; only
   zero-priced ("free") routes enter the pool. The gateway's
   `orchestrator/free` virtual id fails closed (`400 invalid_model`) unless an
   enabled zero-cost agent exists, which our catalog guarantees.
3. **ZDR-first selection**: `scripts/ci/zdr_policy.py` defines ZDR the way
   OpenRouter does ("a provider will not store your data for any period of
   time"; zero retention also implies no training) and is deliberately
   conservative: any provider whose zero-retention guarantee cannot be
   attested from a machine-readable, dated source is treated as non-ZDR,
   mirroring OpenRouter's stance on unascertained policies. The
   OpenRouter `/api/v1/endpoints/zdr` feed (documented, auto-updated) is
   fetched when egress allows it and is authoritative for the `openrouter`
   scope. Its normalized model identity also qualifies a matching discovered
   row from another provider when the final model component is unambiguous;
   ambiguous suffixes receive no grant. Otherwise the dated static attestation
   table is used, never a fabricated policy.
   `scripts/ci/contextual_orchestrator_review_policy.py` turns the free-tier
   discovery report into a ZDR-prioritized, provider-family-diverse agents
   catalog (primary/secondary NVIDIA keys share one outage-domain family),
   capped in size, in the orchestrator's own `ModelAgent` schema.
4. **Wiring**: `pr-review-autofix.yml` and the Required OpenCode dispatch
   provision the sidecar with the five secrets before OpenCode runs and point
   every model/diagnosis candidate at `contextual-orchestrator/orchestrator/free`;
   the generated dispatch config contains only the gateway provider. The shared
   `opencode.jsonc` default `model`/`small_model` is the same gateway route.
   `noema-review.yml` and `strix.yml` provision the same sidecar and use the
   loopback chat-completions/API-compatible URL with virtual model
   `orchestrator/free`; Strix has no external fallback and private targets pass
   visibility through to the gateway's ZDR requirement. Noema reviewer identity
   remains `NOEMA_REVIEW_TOKEN` / GitHub App / OIDC and is still never
   `github.token`; Autofix mutation still requires `PR_REVIEW_MERGE_TOKEN` /
   `OPENCODE_APPROVE_TOKEN` / the exchanged OpenCode app token, never
   `github.token`; model subprocesses still run with
   `GITHUB_TOKEN`/`GH_TOKEN`/OIDC request env stripped.
5. **Evidence**: the sidecar writes a discovery report, the policy report (pool,
   counts, ZDR sources, feed-used flag, selected routes), and exports
   `CONTEXTUAL_ORCHESTRATOR_EVIDENCE`; these are auditable per run.
6. **Review request envelope**: the library keeps its generic 64 KiB default,
   while this loopback, bearer-authenticated, per-job sidecar configures a
   512 MiB ceiling so inline image inputs can reach routing. This follows the
   OpenAI image-input limit of 512 MB total payload per request; it is not
   treated as a universal JSON default or as the Files API's separate 512 MB
   per-file limit. The sidecar startup probe verifies the configured HTTP
   boundary before any review model runs.

## Consequences

- The autofix/OpenCode review paths no longer hard-code any provider base URL
  or model id; upstream model selection is delegated to the orchestrator's
  discovery + cost routing, under the zero-cost pool, with ZDR routes first.
- Workers need egress to the five provider model-list hosts and, when reachable,
  `https://openrouter.ai/api/v1/endpoints/zdr`; the feed failure path is
  graceful (static table).
- A new central dep (vendored repo pinned to a SHA) must be reviewed when the
  orchestrator upgrades; the pin is centralized in one script and one contract
  test.
- `noema-review.yml`, `strix.yml`, and the Required OpenCode dispatch now
  review through the same gateway; direct provider model routes and Strix
  external fallbacks are gone from these required workflows. Reviewer and
  mutation identities are unchanged. The hourly-review-repair roster is not
  collapsed here.

## References (and ZDR standardization)

- OpenRouter. (2026, August). *Zero data retention* [Documentation]. https://openrouter.ai/docs/guides/features/zdr
- OpenRouter. (2026, August). *Provider logging: Data retention & logging* [Documentation]. https://openrouter.ai/docs/guides/privacy/provider-logging
- OpenRouter. (n.d.). *List all models and their properties* API reference; the per-model data-retention metadata (`data_retention: crichton | none`) and the ZDR endpoint feed `https://openrouter.ai/api/v1/endpoints/zdr` are consumed at runtime.
- ContextualWisdomLab/contextual-orchestrator. (2026, August 18). *AGENTS.md*, section “Policy change” — org migration of OpenCode/Noema/Strix to the gateway with the five KV credentials and auto-discovery.
- OpenAI. (n.d.). *Images and vision: Image input requirements*.
  https://developers.openai.com/api/docs/guides/images-vision
- OpenAI. (n.d.). *Create file* [API reference].
  https://developers.openai.com/api/reference/resources/files/methods/create

- **Private-target boundary (2026-08-27):** Noema resolves target visibility with
  the selected repository-scoped reviewer token. Private/internal repositories
  set `CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR=true`; the catalog then excludes
  every non-ZDR route and fails closed when no attested free ZDR route exists.
