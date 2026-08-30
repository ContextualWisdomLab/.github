# ADR-0003: Vendored contextual-orchestrator review sidecar with governed gateway pools

- Status: accepted; **the Strix-specific `orchestrator/auto` split (Decision
  §4, the `strix.yml` wiring bullet) is refined 2026-08-30 by
  [ADR-0020](0020-strix-orchestrator-free-pool.md)** into an evidence-gated
  conditional — Strix routes through `orchestrator/free` only when
  `free_family_diversity >= 2`, falling back to `orchestrator/auto`
  otherwise. Neither pool is retired: `orchestrator/auto` remains the
  fail-closed default whenever the free catalog cannot show independent
  provider-family coverage. The rest of this ADR (vendoring, discovery,
  ZDR-first policy, the family-diverse catalog) remains in force unchanged.
  See the Amendment below.
- Date: 2026-08-27
- Scope: ContextualWisdomLab/.github central review pipelines (OpenCode autofix/dispatch + shared `opencode.jsonc` default + required Noema + Strix review)
- Decision: Route every central CI review write/model execution that touches contracts in this repository through the **vendored** `contextual-orchestrator` gateway, served as a per-runner sidecar. OpenCode and Noema retain the fail-closed zero-cost virtual model id `orchestrator/free`; authoritative Strix security analysis uses the provider-diverse `orchestrator/auto` pool. Strix is intentionally correctness-first rather than zero-cost. **Zero Data Retention (ZDR)-compliant routes remain mandatory for private targets.**
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

## Addendum (2026-08-30): `free_family_diversity` evidence added (#1433)

The 2026-08-30 owner directive (`docs/product-goal-directive.md` §8, and its
same-date instance-specific instruction) asked that Noema, OpenCode, *and*
Strix all route through `contextual-orchestrator`'s `orchestrator/free` pool.
Noema and OpenCode already did. Strix did not, and an initial attempt to flip
that pin unconditionally (#1437, first draft) was rejected on exact-head
review: the source itself acknowledged that the 2026-08-29 single-family
outage-domain finding below was not eliminated, and an unconditional flip
would have reintroduced the exact availability regression this ADR's original
Strix split existed to prevent.

`ContextualWisdomLab/.github#1433` added the missing evidence instead of
flipping the pin on the strength of the instruction alone:
`scripts/ci/contextual_orchestrator_review_policy.py` now reports
`free_family_diversity`, the count of distinct outage-domain provider
families (see `provider_family`) among *all* discovered free routes,
independent of which pool is requested. This turns "is it safe to run Strix
on a strict free pool right now" from a static assumption into evidence
recomputed on every discovery run, consistent with this ecosystem's "no
heuristics without evidence" convention (`docs/product-goal-directive.md`
§6). #1433 deliberately left `strix.yml` untouched, tracking the wiring as a
follow-up (`strix.yml` is a `pull_request_target` required workflow needing
its own reviewed, same-head-checked change).

## Amendment (2026-08-30): Strix wired to the diversity gate (ADR-0020, #1437)

[ADR-0020: Evidence-gated `orchestrator/free` for Strix](0020-strix-orchestrator-free-pool.md)
is the follow-up #1433 tracked and the corrected form of #1437's first draft.
It wires `strix.yml`'s model-resolution step to read `free_family_diversity`
from the sidecar's policy report (`CONTEXTUAL_ORCHESTRATOR_EVIDENCE`) and
select `orchestrator/free` only when it is `>= 2` (the free catalog spans at
least two independent outage domains, so one provider's outage cannot black
out Strix review); otherwise it falls back to `orchestrator/auto`, the same
pool Decision §4 above originally pinned. A negative fixture
(`tests/test_strix_contextual_orchestrator_contract.py`) proves a diversity
of 0 or 1 keeps the resolved model on `orchestrator/auto` rather than
weakening it to `orchestrator/free` — the regression this whole mechanism
exists to prevent.

This is a refinement of Decision §4, not a supersession: `orchestrator/auto`
is not retired, and neither is the correctness-first fallback OpenCode/Noema
never needed but Strix still might. ADR-0020 records the residual risk this
refinement does not claim to fully close (which providers currently publish a
free tier is a live-market condition; a passing diversity count is necessary
but not sufficient evidence of resilience) and a separate, orthogonal
reliability gap — request-time failover when a selected `orchestrator/free`
route errors, as opposed to catalog-time family diversity — that a dedicated
fix in `contextual-orchestrator` is addressing independently of this
repository; ADR-0020 states plainly whether that fix has landed as of this
PR.

These two additions are the conflict-resolution artifacts
`docs/product-goal-directive.md` requires when the directive and an existing
accepted decision disagree: neither silently kept the old pin nor silently
adopted the new instruction, and
`docs/doctoring/contextual-orchestrator-strix-free-diversity-evidence.md`
records the trail.
