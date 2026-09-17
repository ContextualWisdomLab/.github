# ADR-0033: Noema decides semantic-version bumps for central releases

- Status: Accepted
- Date: 2026-09-17
- Deciders: ContextualWisdomLab/.github lead (owner direction via coordinator)

## Context

ADR-0032 centralises the provenance-gated release-tag / publish-package
pair. Version numbers were still a human `workflow_dispatch` input, which
lets a patch release ship a removed public symbol (or an ADR-0028
required-arg promotion) without an independent check.

Owner direction: Noema must classify the bump as `major` / `minor` /
`patch` under semver.org 2.0.0 from collected evidence before the cut,
fail closed when unavailable / low-confidence / conflicting with detected
breaking changes, and record the verdict in release provenance and notes.

## Decision

1. `scripts/ci/noema_semver_bump.py` is the fail-closed gate. It accepts an
   evidence pack (changelog fragments, removed/renamed public symbols,
   required-arg promotions, deprecated-alias-only list, commit/PR titles),
   asks Noema (or a recorded fixture via
   `NOEMA_SEMVER_RECORDED_RESPONSE_PATH`) for
   `{bump, reason, evidence_refs, confidence}`, enforces a minimum
   confidence, rejects `patch`/`minor` when breaking refs are present, and
   computes `release_version` from the previous tag.
2. Rules encoded as independent detectors (not only LLM judgment):
   - removed / renamed public symbols → breaking
   - unsourced-default removals that make arguments required (ADR-0028) →
     breaking
   - deprecated-alias-only → minor (not breaking)
3. The reusable `release-tag.yml` workflow runs the gate by default
   (`decide_version_with_noema: true`), checking out
   `central_workflows_ref` (must match the `uses:` pin) for the script.
   Optional `release_version` input must match the Noema-computed version.
4. Contract tests cover recorded happy / unavailable / low-confidence /
   breaking-conflict paths under `tests/fixtures/noema_semver/`.

## Consequences

- Releases stop for a human when Noema cannot decide safely.
- Product repos must supply a rich `release-evidence.json` for accurate API
  surface detection (fast-mlsirm: `python/fast_mlsirm` public callables +
  PyO3 signatures); the workflow synthesizes a minimal pack otherwise.
- Next fast-mlsirm release (e.g. v0.12.0 if Noema chooses minor from
  0.11.x) must run through this path after adopting the thin callers from
  ADR-0032.
