# ADR-0033: Noema decides semantic-version bumps for central releases

- Status: Proposed
- Date: 2026-09-17
- Deciders: ContextualWisdomLab/.github lead (owner direction via coordinator)

## Context

ADR-0032 centralises the provenance-gated release-tag / publish-package
pair. Version numbers were still a human `workflow_dispatch` input, which
lets a patch release ship a removed public symbol (or an ADR-0028
required-arg promotion) without an independent check.

Owner direction: Noema may classify the bump as `major` / `minor` /
`patch` under semver.org 2.0.0 only after a calibrated fast-mlsirm decision
receipt and immutable contextual-orchestrator client/schema exist. Until then,
the automatic path fails closed and an explicit operator-selected version is
required.

## Decision

1. `scripts/ci/noema_semver_bump.py` is the fail-closed gate. It accepts an
   evidence pack (changelog fragments, removed/renamed public symbols,
   required-arg promotions, deprecated-alias-only list, commit/PR titles),
   loads a recorded Noema verdict via
   `NOEMA_SEMVER_RECORDED_RESPONSE_PATH` for
   `{bump, reason, evidence_refs, confidence}` only as a non-production
   fixture shape. A model-reported confidence scalar is not calibrated release
   authority. Automatic release-version computation remains disabled. Live
   `NOEMA_LLM_API_URL` / `CONTEXTUAL_ORCHESTRATOR_BASE_URL` /
   `NOEMA_LLM_API_KEY` / `NOEMA_LLM_MODEL` transport is rejected until
   contextual-orchestrator publishes a pinned immutable client/schema
   (gateway-token-only, `orchestrator/free`, null default model timeout).
2. Rules encoded as independent detectors (not only LLM judgment):
   - removed / renamed public symbols → breaking
   - unsourced-default removals that make arguments required (ADR-0028) →
     breaking
   - deprecated-alias-only → minor (not breaking)
3. The reusable `release-tag.yml` workflow defaults
   `decide_version_with_noema` to `false`. Setting it to `true` fails
   closed until fast-mlsirm publishes the calibrated decision receipt and
   contextual-orchestrator publishes the immutable gateway client/schema.
   The active path requires an explicit `release_version`. Missing evidence
   is never replaced by a synthesized API-surface pack.
4. Contract tests cover recorded happy / unavailable / low-confidence /
   breaking-conflict paths under `tests/fixtures/noema_semver/`, and the
   sibling-caller pin contract pins the workflow input names and defaults.

## Consequences

- Automatic Noema release decisions are unavailable while calibration and
  immutable-client prerequisites are Proposed.
- Product repos must supply a rich `release-evidence.json` with
  `api_surface_inspected: true` (or concrete API-surface findings) for
  accurate public-API detection (fast-mlsirm: `python/fast_mlsirm` public
  callables + PyO3 signatures). Missing evidence fails closed; the workflow
  does not synthesize an empty API-surface pack.
- Next fast-mlsirm release (e.g. v0.12.0 if Noema chooses minor from
  0.11.x) must run through this path after adopting the thin callers from
  ADR-0032.
