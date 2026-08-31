# ADR-0003: Vendored contextual-orchestrator review sidecar with governed gateway pools

- Status: accepted, amended 2026-08-30 (see "2026-08-30 amendment" below — Strix
  now uses `orchestrator/free`, not the `orchestrator/auto` this header
  originally recorded)
- Date: 2026-08-27
- Scope: ContextualWisdomLab/.github central review pipelines (OpenCode autofix/dispatch + shared `opencode.jsonc` default + required Noema + Strix review)
- Decision: Route every central CI review write/model execution that touches contracts in this repository through the **vendored** `contextual-orchestrator` gateway, served as a per-runner sidecar. OpenCode, Noema, and (as of the 2026-08-30 amendment) Strix all use the fail-closed zero-cost virtual model id `orchestrator/free`. **Zero Data Retention (ZDR)-compliant routes remain mandatory for private targets.**
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
   (`30c6d71680e659f25a0a433d4726ad0d437f9757` today) into `RUNNER_TEMP`. The
   source's `requirements.lock` is installed with `--require-hashes` and
   `--no-deps`, so dependency resolution cannot silently move the reviewed
   runtime.
   runtime entry (`contextual_orchestrator_review_launcher.py`) registers the
   five provider secrets plus the gateway bearer token into the process-local
   KV in the **same process** that performs model discovery and serves
   `/v1/chat/completions` and `/v1/responses` on loopback. Env is bootstrap
   transport only; request-time credential reads go through the KV.
2. **Auto model discovery + governed virtual pools**: discovery runs with the
   orchestrator's own `discover_all_models()` against the KV credentials.
   OpenCode and Noema admit only zero-priced routes. Strix admits two explicit
   evidence tiers: zero-priced first, then routes with finite,
   nonnegative prompt and completion prices plus an explicit currency. Routes
   without a complete published price vector remain counted for audit but are
   not admitted to CI review. A missing pair is never relabeled free or
   price-attested; a partial price vector, malformed numeric value, conflicting
   free marker, or missing currency for a published vector fails closed. The gateway's
   `orchestrator/free` virtual id fails closed (`400 invalid_model`) unless an
   enabled zero-cost agent exists. Strix uses `orchestrator/auto`; its catalog
   may admit priced routes only through this evidence-bearing
   policy, never through a direct-provider model identifier.
   The auto pool probes the free catalog first. Only when every selected free
   route rejects the real runtime request contract does it rebuild once from
   fully price-attested routes and record the rejected primary attempt. This is
   evidence-triggered failover, not an arbitrary free/paid mixing ratio.
   Both stages share one twelve-route startup budget: no more than eight routes
   enter the free primary stage and only its remaining capacity may enter priced
   fallback. Full discovery counts remain in policy evidence, and the transient
   priced catalog is removed immediately after loading.
3. **ZDR-first within each cost tier**: `scripts/ci/zdr_policy.py` defines ZDR
   the way OpenRouter does ("a provider will not store your data for any period
   of time"; zero retention also implies no training) and is deliberately
   conservative: any provider whose zero-retention guarantee cannot be
   attested from a machine-readable, dated source is treated as non-ZDR,
   mirroring OpenRouter's stance on unascertained policies. The
   OpenRouter `/api/v1/endpoints/zdr` feed (documented, auto-updated) is
   fetched when egress allows it and is authoritative for the `openrouter`
   scope; otherwise the dated static attestation table is used, never a
   fabricated policy.
   For private targets, ZDR admission is applied before choosing the cost tier.
   A discovered but non-ZDR free route therefore cannot suppress an attested
   priced route; when an admitted free tier exists it remains the exclusive
   primary, and the admitted priced tier remains fallback-only.
   `scripts/ci/contextual_orchestrator_review_policy.py` turns the discovery
   report into a free-first, cost-evidence-ranked, ZDR-prioritized,
   provider-family-diverse agents catalog (primary/secondary NVIDIA keys share
   one outage-domain family), capped in size, in the orchestrator's own
   `ModelAgent` schema.
4. **Wiring**: `pr-review-autofix.yml` and the Required OpenCode dispatch
   provision the sidecar with the five secrets before OpenCode runs and point
   every model/diagnosis candidate at `contextual-orchestrator/orchestrator/free`;
   the generated dispatch config contains only the gateway provider. The shared
   `opencode.jsonc` default `model`/`small_model` is the same gateway route.
   `noema-review.yml` retains `orchestrator/free`. `strix.yml` provisions the
   same sidecar and uses the loopback chat-completions/API-compatible URL with
   `orchestrator/auto`: the 2026-08-29 exact-head DiskSage scan proved that four
   discovered free routes all shared the OpenRouter outage domain, which the
   gateway correctly collapsed to one provider attempt. Strix therefore uses
   the provider-diverse pool supplied by all five configured credentials.
   Provider diversity and cost-evidence classification remain delegated to the
   gateway rather than embedding a second routing policy in GitHub Actions.
   Strix has no external fallback and private targets pass visibility through
   to the gateway's ZDR requirement. Noema reviewer identity remains
   `NOEMA_REVIEW_TOKEN` / GitHub App / OIDC and is still never `github.token`;
   Autofix mutation still requires `PR_REVIEW_MERGE_TOKEN` /
   `OPENCODE_APPROVE_TOKEN` / the exchanged OpenCode app token, never
   `github.token`; model subprocesses still run with
   `GITHUB_TOKEN`/`GH_TOKEN`/OIDC request env stripped.
5. **Evidence**: the sidecar writes a discovery report, the policy report (pool,
   total/free/priced/unknown counts, selected counts by admitted cost tier, ZDR
   sources, feed-used flag, selected routes), and exports
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
  discovery under the zero-cost pool. Strix uses the separately governed auto
  pool without treating absent price metadata as either free or paid-route
  evidence.
- Strix delegates selection to `orchestrator/auto`. Its correctness-first pool
  remains distinct from the zero-cost OpenCode/Noema pool, while private-target
  ZDR admission remains fail-closed. Unknown-cost routes remain auditable but
  ineligible; free and fully price-attested routes are the only review routes.
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
  every non-ZDR route and fails closed when no attested ZDR route exists in the
  selected workflow pool.

- **2026-08-30 amendment: Strix uses `orchestrator/free`, superseding this
  ADR's original `orchestrator/auto` decision.** The org owner explicitly
  directed Strix off the paid-inclusive `orchestrator/auto` pool and onto the
  same zero-cost `orchestrator/free` pool OpenCode and Noema already use, so
  no central review path executes a paid model. This is a deliberate,
  informed override of the original decision above, not an oversight of it:
  the trade-off the original decision recorded — "the 2026-08-29 exact-head
  DiskSage scan proved that four discovered free routes all shared the
  OpenRouter outage domain, which the gateway correctly collapsed to one
  provider attempt... Strix has no external fallback" — was surfaced to the
  owner explicitly, including a live 2026-08-30 reproduction of that same
  single-family-collapse pattern (a `strix` run's `orchestrator/auto`
  primary/free stage rejected 4/4 candidates — 2 timeouts, 2 HTTP 404s from
  retired NVIDIA-hosted models — and only the `auto` pool's paid fallback
  kept that run alive; see `docs/product-technical-gap-baseline.md`'s
  2026-08-30 sidecar-preflight entries for the full evidence trail). The
  owner's response, verbatim in substance: implement the free-only directive
  as originally instructed. **Accepted consequence**: Strix has no external
  fallback and can go fully dark (rather than degraded-but-running) during
  the exact class of incident this ADR originally used `orchestrator/auto`
  to survive, until the free-catalog's stale-model and provider-diversity
  gaps documented alongside this amendment are separately closed. This is
  the owner's accepted risk, not an unnoticed regression.
  `scripts/ci/strix_quick_gate.sh`'s `is_contextual_orchestrator_model` no
  longer accepts `orchestrator/auto`; `strix.yml`'s `STRIX_MODEL`/
  `CONTEXTUAL_ORCHESTRATOR_POOL` default to `orchestrator/free`; and
  `scripts/ci/strix_required_workflow_smoke.sh`/`AGENTS.md` were updated to
  match. The `orchestrator/auto` pool mode itself is unchanged and still
  exists in `contextual_orchestrator_review_policy.py`/the sidecar for any
  other caller that opts into it explicitly — this amendment only removes it
  as Strix's default and as an accepted Strix override value.
- **Monitoring evidence for the accepted risk above:** `scripts/ci/contextual_orchestrator_review_policy.py`
  now reports `free_family_diversity` in the catalog report — the count of
  distinct outage-domain provider families (see `provider_family`) among
  *all* discovered free routes, independent of which pool is requested. This
  was drafted (in a now-superseded addendum proposing to gate the `free`
  decision on this evidence rather than making it directly) before the
  2026-08-30 amendment above settled the question outright; the owner chose
  to accept the risk rather than wait. The evidence itself remains useful
  regardless: it is exactly the live signal for when "the free-catalog's
  stale-model and provider-diversity gaps documented alongside this
  amendment" (above) are closed, without requiring a manual re-audit.
  `docs/doctoring/contextual-orchestrator-strix-free-diversity-evidence.md`
  records that PR's own reasoning trail.
