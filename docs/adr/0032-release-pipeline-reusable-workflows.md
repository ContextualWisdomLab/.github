# ADR-0032: Release pipeline reusable workflows

- Status: Accepted
- Date: 2026-09-17
- Deciders: ContextualWisdomLab/.github lead (owner direction via coordinator)

## Context

`fast-mlsirm` owns a carefully fail-closed release pair:

- `.github/workflows/release-tag.yml` — `workflow_dispatch` cut that verifies
  default-branch dispatch, 40-char `release_commit`, ancestry, pyproject
  version, exactly one CHANGELOG section, version-cut vs parent, fragment
  drift, size-capped notes, refuse-overwrite of existing releases, then
  `gh release create --verify-tag --notes-file` and dispatches publication.
- `.github/workflows/publish-pypi.yml` — provenance re-check, pinned maturin
  sdist/wheels, immutable-release-aware asset attach, PyPI publish under the
  `pypi` environment.

Other Python / Rust-extension repos will need the same contract. Copying the
pair per repo reintroduces pin drift and silent weakening of provenance
checks. Org pattern for this class of consolidation is already established
by ADR-0023 (R CMD check) and ADR-0024 (Dependency Review): reusable
`workflow_call` in `.github`, thin callers in product repos, pin `uses:` to
an exact commit SHA.

## Decision

1. Add `.github/workflows/release-tag.yml` and
   `.github/workflows/publish-package.yml` in ContextualWisdomLab/.github as
   `workflow_call`-only reusable workflows, preserving every fail-closed
   check and the release-validated action SHAs from fast-mlsirm.
2. Parameterise only genuine per-repo policy:
   - `packaging_backend`: `maturin` | `pure-python`
   - `publish_to_pypi` / `pypi_environment` / optional `PIPY_TOKEN`
   - `publish_workflow` filename for the post-release dispatch
   - optional changelog fragment check and path overrides
3. fast-mlsirm (and later adopters) keep thin `workflow_dispatch` wrappers
   that call the reusable workflows at an exact SHA. Local full copies are
   deleted only after one successful end-to-end release through the central
   path. Required check names must be updated if job nesting renames them.
4. Contract tests pin the reusable workflow prose the same way other central
   workflows are pinned.
5. Sibling-caller pin contract (durable adoption surface after merge) is
   recorded in
   [`docs/doctoring/release-pipeline-reusable-workflows.md`](../doctoring/release-pipeline-reusable-workflows.md)
   § "Sibling-caller pin contract": exact
   `uses: ContextualWisdomLab/.github/.github/workflows/release-tag.yml@<sha>`
   /
   `uses: ContextualWisdomLab/.github/.github/workflows/publish-package.yml@<sha>`
   patterns, required inputs including the Noema bump gate and matching
   `central_workflows_ref`, and the rule that reusable targets stay
   `workflow_call`-only (no `pull_request` / `push` / `workflow_dispatch`).

## Consequences

- One reviewed provenance implementation; product repos cannot silently drop
  a gate by editing a local copy.
- Adopters must pin `uses:` to a commit SHA (never `@main`) and pass the
  same SHA as `central_workflows_ref` on release-tag (ADR-0033).
- Semver bumps are decided by Noema under ADR-0033 before the tag is cut.

## Amendment (2026-09-28): production lineage is not the default branch

The default branch remains the control plane that dispatches the caller
workflow. It is production authority only when it is protected `main` or
`master` (GitHub Flow). When the default branch is anything else, including
`develop`, release admission requires an explicit protected production branch
named `main` or `master`, and `release_commit` must be an ancestor of that
branch tip.
Develop-only ancestry is rejected. An unprotected production branch fails
closed. `control_plane_commit` on package publication is the dispatch SHA,
not production-branch authority. Product repositories do not copy this
classification; they call the central workflow at an exact SHA and pass
`production_branch` only when their default branch is not already `main` or
`master`.
- Next adoption candidates after fast-mlsirm e2e success: other maturin /
  PyPI packages in the org (survey at adoption time; do not assume from this
  ADR alone).
