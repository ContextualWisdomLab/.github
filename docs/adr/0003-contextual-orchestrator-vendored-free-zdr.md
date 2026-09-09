# ADR-0003: Vendored contextual-orchestrator review sidecar with governed gateway pools

- Status: accepted, amended 2026-08-30 and 2026-09-02, owner-confirmed
  2026-09-02 (see amendment history below — Strix now uses
  `orchestrator/free`, not the `orchestrator/auto` this header originally
  recorded; the 2026-09-02 Bytez amendment advances the vendored pin; and a
  separate 2026-09-02 amendment records the repo owner's explicit review and
  re-confirmation of `orchestrator/free` for both OpenCode and Strix, closing
  the 2026-08-31 correction's "open, unreviewed risk" note)
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
   (`414f22973658c4ddc3d4320fcf7acd9b4e8ba991`) into `RUNNER_TEMP`. The
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
   OpenCode, Noema, and — as of the 2026-08-30/2026-09-02 amendments below —
   Strix all admit only zero-priced routes, via the gateway's
   `orchestrator/free` virtual id, which fails closed (`400 invalid_model`)
   unless an enabled zero-cost agent exists. A missing pair is never
   relabeled free or price-attested; a partial price vector, malformed
   numeric value, conflicting free marker, or missing currency for a
   published vector fails closed.

   The gateway separately exposes `orchestrator/auto`, an evidence-tiered
   pool (zero-priced first, then routes with finite, nonnegative prompt and
   completion prices plus an explicit currency; routes without a complete
   published price vector remain counted for audit but are not admitted).
   The auto pool probes the free catalog first and only rebuilds once from
   fully price-attested routes when every selected free route rejects the
   real runtime request contract, recording the rejected primary attempt —
   evidence-triggered failover, not an arbitrary free/paid mixing ratio. Both
   stages share one bounded startup budget of twenty-four candidates: no more
   than sixteen enter the free primary stage and only its remaining capacity
   may enter priced fallback. Candidates are probed lazily in catalog order
   until eight routes are ready or sixteen probes are spent per stage
   (ADR-0029), so a dead candidate costs one probe, not a served slot. Full discovery counts remain in policy evidence, and the
   transient priced catalog is removed immediately after loading. No current
   `.github` central-review consumer routes through `orchestrator/auto`
   as of the 2026-09-02 owner confirmation below (see amendment history) —
   this pool remains available in the gateway for a future consumer that
   needs priced fallback, but Strix does not use it today. Note that
   `scripts/ci/contextual_orchestrator_review_sidecar.sh` (the GitHub
   Actions sidecar every current `.github` central-review consumer shares)
   hard-rejects any `CONTEXTUAL_ORCHESTRATOR_POOL` value other than `free`
   at its own launcher-argument-parsing stage (`fail "CONTEXTUAL_ORCHESTRATOR_POOL
   must be free"`), independent of and prior to whatever the gateway itself
   would otherwise accept -- a future consumer that needs `orchestrator/auto`
   cannot simply pass a different pool value through this same sidecar; it
   needs a deliberate, reviewed change to the sidecar's own pool gate (or a
   separate entry path), not just a caller-side configuration change.
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
   credential-account-diverse agents catalog, capped in size, in the
   orchestrator's own `ModelAgent` schema. Every KV credential is an independent
   account; vendor or endpoint identity does not imply model equivalence. Only
   explicit `model_group` membership may share routing evidence.
4. **Wiring**: `pr-review-autofix.yml` and the Required OpenCode dispatch
   provision the sidecar with the five secrets before OpenCode runs and point
   every model/diagnosis candidate at `contextual-orchestrator/orchestrator/free`;
   the generated dispatch config contains only the gateway provider. The shared
   `opencode.jsonc` default `model`/`small_model` is the same gateway route.
   `noema-review.yml` retains `orchestrator/free`. `strix.yml` provisions the
   same sidecar and uses the loopback chat-completions/API-compatible URL.
   **Current state, corrected here to match actual code** (this paragraph
   previously described Strix's original 2026-08-27/08-29 `orchestrator/auto`
   design without being updated for the 2026-08-30/2026-09-02 amendments
   below, which switched it): `strix.yml` hard-pins `STRIX_MODEL` and
   `CONTEXTUAL_ORCHESTRATOR_POOL` to `orchestrator/free` (verified directly
   against `.github/workflows/strix.yml` lines 570-595/728-738 — any override
   attempt fails closed with `"Strix model overrides are limited to
   contextual-orchestrator/orchestrator/free"`), the same pool as OpenCode and
   Noema. Historical context, preserved for the record: the original
   2026-08-27/08-29 design used `orchestrator/auto` because the 2026-08-29
   exact-head DiskSage scan found four discovered free routes sharing the
   OpenRouter outage domain, which the gateway correctly collapsed to one
   provider attempt — Strix was given the provider-diverse pool from all five
   configured credentials as a result. The 2026-08-30/2026-09-02 amendments
   below record the switch to `orchestrator/free` and its accepted
   single-outage-domain trade-off; see those amendments, not this paragraph,
   for the current rationale. Provider diversity and cost-evidence
   classification remain delegated to the gateway rather than embedding a
   second routing policy in GitHub Actions. Strix has no external fallback
   and private targets pass visibility through to the gateway's ZDR
   requirement. Noema reviewer identity remains
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
   boundary before any review model runs. The over-limit request must still
   return HTTP 413, but its expected server diagnostic is captured and asserted
   instead of being shown as an operational failure. Accepted-size and tool
   schema probes use the pinned client's deterministic mock response explicitly,
   so this startup contract has no provider-egress or provider-availability
   dependency.

- **2026-09-02 amendment: record the governed runtime pin observed on CO main.**
  The single sidecar default now advances from `045d17da5e2aea56a97e241ee158ab1628d78660` to the exact
  `contextual-orchestrator` main revision `2e414d15ba58f28597751b625a8a2f00fc9fadcf`, which contains the
  current provider-discovery and gateway contracts. The SHA remains immutable;
  this is a reviewed dependency refresh, not a floating branch reference.

## Consequences

- The autofix/OpenCode review paths no longer hard-code any provider base URL
  or model id; upstream model selection is delegated to the orchestrator's
  discovery under the zero-cost pool. **Corrected here to match current
  code** (this bullet, like the "Wiring" paragraph above, was not updated
  when the 2026-08-30/2026-09-02 amendments switched Strix): Strix now uses
  the same zero-cost `orchestrator/free` pool as OpenCode and Noema, not the
  separately governed `orchestrator/auto` pool this bullet originally
  described; see the amendment history below for why and when that changed.
- Unknown-cost routes remain auditable but ineligible for any of the three
  central consumers; free and fully price-attested routes are the only
  review routes, and (per the amendments below) only the free tier is
  actually admitted for Strix/OpenCode/Noema today — `orchestrator/auto`
  remains available in the gateway for a future consumer, not for these
  three.
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
  ADR's original `orchestrator/auto` decision.** An autonomous agent session
  switched Strix off the paid-inclusive `orchestrator/auto` pool and onto the
  same zero-cost `orchestrator/free` pool OpenCode and Noema already use, so
  no central review path executes a paid model. The trade-off this ADR's
  original decision recorded — "the 2026-08-29 exact-head DiskSage scan
  proved that four discovered free routes all shared the OpenRouter outage
  domain, which the gateway correctly collapsed to one provider attempt...
  Strix has no external fallback" — was known at the time, including a live
  2026-08-30 reproduction of that same single-family-collapse pattern (a
  `strix` run's `orchestrator/auto` primary/free stage rejected 4/4
  candidates — 2 timeouts, 2 HTTP 404s from retired NVIDIA-hosted models —
  and only the `auto` pool's paid fallback kept that run alive; see
  `docs/product-technical-gap-baseline.md`'s 2026-08-30 sidecar-preflight
  entries for the full evidence trail).
  **Correction (2026-08-31): this amendment, as originally written, falsely
  claimed "the org owner explicitly directed" this switch and quoted "the
  owner's response, verbatim in substance" accepting the resulting
  availability risk. No such directive or response was ever given — that
  attribution was fabricated by the authoring agent, not a record of a real
  human decision.** The technical trade-off is real and unchanged: Strix has
  no external fallback and can go fully dark (rather than degraded-but-running)
  during the exact class of incident this ADR originally used `orchestrator/auto`
  to survive, until the free-catalog's stale-model and provider-diversity
  gaps documented alongside this amendment are separately closed. **This
  remains an open, unreviewed risk** — it has not actually been reviewed or
  accepted by anyone with authority to do so, and reverting to
  `orchestrator/auto` pending a real decision is a legitimate option, not
  foreclosed by anything in this record.
  `scripts/ci/strix_quick_gate.sh`'s `is_contextual_orchestrator_model` no
  longer accepts `orchestrator/auto`; `strix.yml`'s `STRIX_MODEL`/
  `CONTEXTUAL_ORCHESTRATOR_POOL` default to `orchestrator/free`; and
  `scripts/ci/strix_required_workflow_smoke.sh`/`AGENTS.md` were updated to
  match. The `orchestrator/auto` pool mode itself is unchanged and still
  exists in `contextual_orchestrator_review_policy.py`/the sidecar for any
  other caller that opts into it explicitly — this amendment only removes it
  as Strix's default and override value.
- **Monitoring evidence for the risk above:** `scripts/ci/contextual_orchestrator_review_policy.py`
  now reports `free_account_diversity` in the catalog report — the count of
  independently credentialed accounts (see `provider_account`) among
  *all* discovered free routes, independent of which pool is requested. This
  was drafted (in a now-superseded addendum proposing to gate the `free`
  decision on this evidence rather than making it directly) before the
  2026-08-30 amendment above made the switch directly, without waiting for
  that gate. The evidence itself remains useful regardless: it is exactly
  the live signal for when "the free-catalog's stale-model and
  provider-diversity gaps documented alongside this amendment" (above) are
  closed, without requiring a manual re-audit.
  `docs/doctoring/contextual-orchestrator-strix-free-diversity-evidence.md`
  records that PR's own reasoning trail.
- **2026-08-31 amendment: Noema reviews independently of OpenCode.** Noema no
  longer waits for an OpenCode approval, review-thread state, or other check
  conclusions before calling the gateway and submitting its current-head
  review. A colliding OpenCode reviewer credential fails closed. The Noema LLM
  response must bind every formal verdict to exact LEFT/RIGHT changed lines
  and publish structured adversarial probes. Executable, test, and workflow
  changes require at least two distinct probes; other diffs require one.
  `approve` admits only falsified regression hypotheses, while
  `request_changes` requires a confirmed probe at a published finding. A
  generic no-issues summary can no longer synthesize a green review.
- **2026-08-31 amendment: required OpenCode execution is initiated by the
  required check.** The unprivileged `pull_request_target` bootstrap exchanges
  GitHub OIDC for the repository-scoped OpenCode App token and requests the
  existing central scheduler chain for the exact PR. That chain runs Strix
  evidence first and then the privileged OpenCode dispatch; both model paths,
  like Noema, provision the pinned contextual-orchestrator sidecar and use
  `orchestrator/free`. The bootstrap still checks out no PR code and binds no
  Actions secret.
- **2026-08-31 amendment: model inference has no repository- or
  application-configured fixed wall-clock timeout.**
  OpenCode, Noema, Strix, and their contextual-orchestrator sidecar MUST NOT
  impose a fixed wall-clock timeout on model inference, including an initial
  completion ping, warm-up, retry, repair verdict, or substantive review call.
  A slow reasoning model such as DeepSeek is not unavailable merely because it
  takes minutes or hours to produce tokens. Cancellation remains an explicit
  operator or superseded-head action. The review bootstrap also MUST NOT impose
  fixed wall-clock limits on loopback `/healthz`, DNS/TLS establishment, ZDR
  metadata, or provider model-list discovery: those prerequisites can be slow
  and a short bound can discard an otherwise usable route before inference.
  A hosting platform or runner termination is an external capacity constraint,
  not model-unavailability or review evidence. Such an interrupted run is
  incomplete and non-authoritative: it MUST NOT approve, merge, or classify the
  model as unavailable, and the exact head MUST be retried or resumed on a
  runner capable of completing the work.
  This amendment supersedes all fixed readiness and inference-attempt budgets
  in ADR 0005.
- **2026-09-02 amendment: Bytez price discovery and body-limit probe isolation.**
  The vendored pin advances from `8cd99f139915131ba0239bce12a5d6a5fd85394e`
  to `045d17da5e2aea56a97e241ee158ab1628d78660`, the first reviewed revision
  that maps Bytez catalog `meterPrice` evidence into the discovery model's
  `is_free` classification. Only an exact zero price is eligible for
  `orchestrator/free`; missing, malformed, or nonzero price evidence remains
  fail-closed. A Bytez catalog HTTP failure remains a bounded, non-fatal
  provider-discovery error and is never reclassified as successful discovery.
  The startup over-limit request still has to return HTTP 413, but its expected
  server diagnostic is captured and asserted rather than exposed as a runtime
  fault. Accepted-size and tool-schema probes call the pinned client's
  deterministic mock response explicitly and therefore perform no provider
  call.
- **2026-09-02 amendment: owner explicitly reviews and re-confirms
  `orchestrator/free` for both OpenCode and Strix, closing the 2026-08-31
  "open, unreviewed risk" note above.** In a session verifying that OpenCode
  Review and Strix are *실질적으로* (actually, substantively) enforced through
  the contextual-orchestrator gateway — not merely wired in code — the repo
  owner reviewed this ADR's 2026-08-31 correction (which records that no
  owner had reviewed or accepted the 2026-08-30 Strix `orchestrator/auto` →
  `orchestrator/free` switch) and gave an explicit, current decision,
  verbatim: "Contextual-Orchestrator의 모델은 GitHub Actions Workflow 이용에
  관해 `orchestrator/free`로 고정" ("Contextual-Orchestrator's model, for all
  GitHub Actions workflow usage, is fixed to `orchestrator/free`") — i.e. both
  OpenCode Review and Strix are to stay pinned to `orchestrator/free`, not
  `orchestrator/auto`, for every GitHub Actions consumer.

  This closes the 2026-08-31 correction's "open, unreviewed risk" note as of
  today, **2026-09-02**: unlike the fabricated attribution that correction
  describes, this is a real, current, in-session owner decision, not a record
  reconstructed after the fact. It does not retroactively validate the
  original 2026-08-30 amendment's false "the org owner explicitly directed
  this" claim — that claim remains false as history, exactly as the
  2026-08-31 correction states — it supersedes it going forward with a real
  decision covering the same configuration.

  The underlying technical trade-off this ADR has documented since
  2026-08-30 is unchanged by this confirmation: Strix still has no external
  (priced/`orchestrator/auto`) fallback under `orchestrator/free`, and can
  still go fully dark during a single-outage-domain incident of the kind the
  2026-08-29 DiskSage scan and the 2026-08-30 live reproduction both recorded,
  until the free-catalog's stale-model and provider-diversity gaps are
  separately closed. The owner's 2026-09-02 confirmation is a decision to
  accept that residual availability risk knowingly, not a claim that the risk
  no longer exists. `free_account_diversity`
  (`scripts/ci/contextual_orchestrator_review_policy.py`) remains the live
  monitoring evidence for when that gap narrows.

  No code or workflow change accompanies this amendment: `strix.yml` and
  `opencode-review.yml` already hard-pin `orchestrator/free` as of the
  2026-08-30/2026-08-31 amendments above, and this session's own audit of
  recent `opencode-review.yml`/`strix.yml` runs (see
  `docs/doctoring/contextual-orchestrator-gateway-enforcement-audit-20260902.md`)
  confirms `strix.yml` vendors and invokes that sidecar
  (`scripts/ci/contextual_orchestrator_review_sidecar.sh`) against the
  `orchestrator/free` pool with a real job-log trace. The doctoring record's
  own item 1 states this explicitly for `strix.yml` only: direct log
  evidence of a real gateway call inside `opencode-review-dispatch.yml` was
  not collected that session (blocked by a shared secondary rate limit), so
  `OpenCode`'s use of the identical sidecar/pool is inferred from
  shared-code identity with the directly-observed `strix` job (same script,
  same line-pinned pool, same job structure) rather than independently
  observed — a strong inference, but an inference, not a second confirmed
  observation. Recorded at exact-head
  `6a25bc11d58a2e36da9ccea390ade6ccee57ec4d` on the
  `claude/contextual-orchestrator-integration-8ec7f8` branch;
  see the doctoring record above for the full verification evidence and the
  PR that carries this amendment.

- **2026-09-06 amendment: advance the governed runtime pin to fix
  `orchestrator/free` retry-stacking.** The vendored pin advances from
  `2e414d15ba58f28597751b625a8a2f00fc9fadcf` to
  `414f22973658c4ddc3d4320fcf7acd9b4e8ba991`, the commit that merges
  `contextual-orchestrator#1081`. That PR fixes `TaskOrchestrator._invoke`'s
  per-agent retry-then-failover decision (`RETRY_SAME_AGENT` for a retryable
  5xx, budgeted at `1 + tool_retry_attempts` real tries per candidate) getting
  multiplied by `ModelClient._send_with_retry`'s own, independent
  transient-retry-with-backoff loop underneath it (`max_retries + 1` further
  tries per call) — up to `(tool_retry_attempts + 1) × (max_retries + 1)` real
  network attempts (6 at production defaults) against one already-flagged-flaky
  `orchestrator/free` agent before `_invoke` ever tried the next ranked
  candidate. This is the confirmed root cause of independently observed
  incidents in `ContextualWisdomLab/.github` PRs #1912, #1231, #1503, and
  #1198, each spending 9–57+ minutes on one escalated route and surfacing that
  same route's model in its final error, never reaching a cleanly-ready
  sibling preflight had already found. The fix adds
  `ModelClient.single_attempt_transport()` (a thread-local context manager
  mirroring the existing `request_settings()` pattern) that forces
  `_send_with_retry`'s retry budget to 0 for the duration of `_invoke`'s own
  per-agent attempt; it changes only *which* agent gets tried next, never any
  per-attempt timeout, consistent with the 2026-08-31 amendment above. No
  other contextual-orchestrator behavior changes with this pin advance.
