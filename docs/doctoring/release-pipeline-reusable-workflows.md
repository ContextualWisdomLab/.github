# Release pipeline reusable workflows

## Decision

Centralise the provenance-gated **release-tag** + **publish-package** pair
that `fast-mlsirm` developed into ContextualWisdomLab/.github as
`workflow_call` reusable workflows. See
[ADR-0032](../adr/0032-release-pipeline-reusable-workflows.md).

## Source audit (fast-mlsirm)

| Concern | release-tag.yml | publish-pypi.yml |
| --- | --- | --- |
| Trigger | `workflow_dispatch` (version + commit) | `workflow_dispatch` (tag + commit + control_plane) |
| Provenance | default-branch ref, 40-char SHA, ancestry, pyproject match, exactly one CHANGELOG section, parent version-cut, optional fragment `--check` | control_plane == `github.sha`, default-branch ref, tag→commit, tag == `v{version}` |
| Notes | CHANGELOG section → `release_notes.md`, 120k body cap with CHANGELOG link fallback | n/a |
| Tag/release | refuse existing release; resume tag only if SHA matches; atomic ref create; `gh release create --verify-tag` | attach assets unless release `.immutable` |
| Publish | `gh workflow run publish-pypi.yml` with control_plane HEAD | maturin sdist + wheel matrix; PyPI via `pypi` env + `pypa/gh-action-pypi-publish` (`skip-existing`) |
| Pins | `actions/checkout@3d3c42e5…` | same checkout/setup-python; `PyO3/maturin-action@e83996d1…`; upload/download-artifact; pypi-publish `@dc37677b…` |

All of the above fail-closed checks and pins are preserved in the reusable
targets. Action SHAs are the release-validated set from fast-mlsirm, not
re-picked.

## Mechanism

| Central file | Role |
| --- | --- |
| `.github/workflows/release-tag.yml` | Reusable cut + GitHub release + optional publish dispatch |
| `.github/workflows/publish-package.yml` | Reusable verify + build + assets + optional PyPI |

### Inputs that stay per-repo

- `packaging_backend`: `maturin` (default) or `pure-python` (`python -m build`)
- `publish_to_pypi` / `pypi_environment` / optional secret `PIPY_TOKEN`
- `publish_workflow` on release-tag (default `publish-pypi.yml` so existing
  operator filenames keep working during migration)
- `run_changelog_fragment_check` (default true; set false if the caller has
  no `scripts/render_changelog_fragments.py`)

## Sibling-caller pin contract

Product repos adopt these workflows **only** through thin local wrappers.
The reusable targets themselves stay `workflow_call`-only: they must never
grow `pull_request`, `push`, or `workflow_dispatch` triggers (contract test
enforced). Callers keep their own `on: workflow_dispatch` (and any branch
restriction); GitHub cannot trigger a `workflow_call` target directly.

### Exact `uses:` pin pattern

Replace `<sha>` with the reviewed ContextualWisdomLab/.github commit that
carries the reusable files (the merge commit of this consolidation, or a
later reviewed bump). Never `@main`, never a floating tag.

| Reusable target | Pin field product repos must copy |
| --- | --- |
| release cut | `uses: ContextualWisdomLab/.github/.github/workflows/release-tag.yml@<sha>` |
| package publish | `uses: ContextualWisdomLab/.github/.github/workflows/publish-package.yml@<sha>` |

The same 40-character lowercase SHA must also be passed as
`central_workflows_ref` on the release-tag call so
`scripts/ci/noema_semver_bump.py` is checked out from that exact revision
(ADR-0033). A mismatched pin vs `central_workflows_ref` is a failed gate,
not a silent drift.

### Required / gate inputs (release-tag)

| Input / secret | Role |
| --- | --- |
| `release_commit` | Required. Full lowercase SHA-1 of the reviewed release source. |
| `central_workflows_ref` | Required for adopters. Same `<sha>` as the `uses:` pin. |
| `decide_version_with_noema` | Default `true`. Noema bump gate (ADR-0033); fail closed on unavailable / low-confidence / breaking-conflict. |
| `release_version` | Optional when Noema decides; if set, must equal the Noema-computed version. Required when `decide_version_with_noema` is false. |
| `min_confidence` | Default `0.7`. Fail closed below this confidence. |
| `evidence_path` | Default `release-evidence.json`. Required when Noema decides; must include `api_surface_inspected: true` or at least one API-surface finding. No synthesized empty-API fallback. |
| `publish_workflow` | Default `publish-pypi.yml`. Empty skips package dispatch. |
| `run_changelog_fragment_check` | Default `true`; set `false` when the caller has no fragment renderer. |
| `NOEMA_SEMVER_RECORDED_RESPONSE_PATH` | Optional repo/org var pointing at a recorded Noema verdict fixture. Live URL/model/API-key clients are fail-closed until contextual-orchestrator publishes a pinned immutable client/schema (ADR-0033). |

### Required inputs (publish-package)

| Input / secret | Role |
| --- | --- |
| `release_tag` | Required. Immutable tag (for example `v0.9.0`). |
| `release_commit` | Required. Full lowercase SHA-1 matching the tag. |
| `control_plane_commit` | Required. Protected default-branch SHA that selected publication (`github.sha` of the dispatch). |
| `packaging_backend` | Default `maturin`; alternate `pure-python`. |
| `publish_to_pypi` / `pypi_environment` | Default true / `pypi`. |
| `PIPY_TOKEN` | Optional secret; prefer OIDC trusted publishing. |

### Example thin callers

**release-tag.yml** (caller):

```yaml
name: Release Tag
on:
  workflow_dispatch:
    inputs:
      release_version:
        required: false
        type: string
      release_commit:
        required: true
        type: string
permissions:
  contents: read
concurrency:
  group: release-tag
  cancel-in-progress: false
jobs:
  publish-release-tag:
    uses: ContextualWisdomLab/.github/.github/workflows/release-tag.yml@<sha>
    with:
      release_commit: ${{ inputs.release_commit }}
      # optional human pin; must match Noema when decide_version_with_noema
      release_version: ${{ inputs.release_version }}
      decide_version_with_noema: true
      central_workflows_ref: <sha>
      publish_workflow: publish-pypi.yml
      run_changelog_fragment_check: true
    secrets: inherit
    permissions:
      contents: write
      actions: write
```

**publish-pypi.yml** (caller; keep the filename during migration):

```yaml
name: Publish Package
on:
  workflow_dispatch:
    inputs:
      release_tag:
        required: true
        type: string
      release_commit:
        required: true
        type: string
      control_plane_commit:
        required: true
        type: string
permissions:
  contents: read
concurrency:
  group: publish-package-${{ inputs.release_tag }}
  cancel-in-progress: false
jobs:
  publish:
    uses: ContextualWisdomLab/.github/.github/workflows/publish-package.yml@<sha>
    permissions:
      contents: write
      id-token: write
    with:
      release_tag: ${{ inputs.release_tag }}
      release_commit: ${{ inputs.release_commit }}
      control_plane_commit: ${{ inputs.control_plane_commit }}
      packaging_backend: maturin
      publish_to_pypi: true
    secrets: inherit
```

Nested reusable jobs publish check names like
`publish / verify release provenance`. If branch protection required a
literal old job name, update the required-check list when adopting.

## Noema semver gate (ADR-0033)

Before the tag is cut, `release-tag.yml` (when `decide_version_with_noema`
is true, the default) runs `scripts/ci/noema_semver_bump.py`:

1. Load caller-supplied `release-evidence.json` (required; no synthesized
   empty-API fallback). The pack must set `api_surface_inspected: true` or
   include at least one API-surface finding (removed/renamed/required-arg).
2. Load a recorded Noema verdict via `NOEMA_SEMVER_RECORDED_RESPONSE_PATH`
   for `{bump, reason, evidence_refs, confidence}` under semver.org 2.0.0
   (live URL/model/API-key clients remain fail-closed until CO publishes a
   pinned client/schema).
3. Fail closed when Noema is unavailable, confidence < `min_confidence`
   (default 0.7), or the verdict under-bumps detected breaking changes
   (removed/renamed public symbols; ADR-0028 required-arg promotions).
   Deprecated-alias-only changes are minor, not breaking.
4. Compute `release_version` from the previous git tag + bump; optional
   human `release_version` input must match.
5. Record `noema-semver-provenance.json` and quote the verdict at the top
   of the GitHub release notes.

Callers must pass `central_workflows_ref` equal to the same 40-char SHA
used in `uses: …/release-tag.yml@<sha>` so the gate script is the reviewed
revision. Live URL/model/API-key clients are fail-closed until
contextual-orchestrator publishes a pinned immutable client/schema; set
`NOEMA_SEMVER_RECORDED_RESPONSE_PATH` (or `decide_version_with_noema:
false` with an explicit `release_version`) until that contract exists.

Contract tests:
`tests/test_noema_semver_bump.py` + fixtures under
`tests/fixtures/noema_semver/` (including unavailable, low-confidence, and
breaking-conflict recorded responses).

## Adoption order

1. **Land** this `.github` PR (workflows + contract tests + this note).
2. **fast-mlsirm**: open a separate PR that replaces local full copies with
   the thin wrappers above, pinned to the merge SHA. Do **not** delete the
   full local copies until one successful end-to-end release has run through
   the central path (immutable-release rules unchanged).
3. **Next candidates** (re-survey at adoption time; not a close instruction):
   other org Python packages that publish to PyPI and/or use maturin — e.g.
   candidates historically adjacent to fast-mlsirm packaging (confirm with
   `gh search` / repo inventory before claiming ownership). Pure-docs or
   non-PyPI repos should not adopt.

## Contract tests

`tests/test_release_pipeline_reusable_workflow_contract.py` pins
`workflow_call`-only triggers (no `pull_request` / `push` /
`workflow_dispatch` on the reusable files), required inputs, provenance
markers, backend gating, action SHAs, OIDC/`pypi` environment wiring,
immutable asset skip behaviour, and the sibling-caller pin fields in this
note plus ADR-0032 (`uses: …@<sha>`, `central_workflows_ref`, Noema bump
gate).
