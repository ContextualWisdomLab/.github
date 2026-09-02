# Dependency Review reusable workflow consolidation

## Decision

`argos`, `mightyETL`, `newsdom-api`, and `scopeweave` each carried an
independently hand-written `.github/workflows/dependency-review.yml` running
`actions/dependency-review-action` on pull requests. All four are replaced by
one new reusable workflow, `.github/workflows/dependency-review.yml` in this
repository, plus a thin `workflow_call` caller left in place of each
repository's own file. See
[ADR-0024](../adr/0024-dependency-review-reusable-workflow-consolidation.md).

## Field-by-field audit

Reading all four files' full bodies (not just the job name and action used)
found real, repo-specific policy differences, not accidental copy drift:

| Field | argos | mightyETL | newsdom-api | scopeweave |
| --- | --- | --- | --- | --- |
| `fail-on-severity` | `moderate` | `high` | unset → action default `low` | unset → action default `low` |
| `allow-ghsas` | none | none | `GHSA-69w3-r845-3855` | none |
| step `continue-on-error` | `true` | unset (blocking) | unset (blocking) | unset (blocking) |
| availability handling | none | static `repository.private` branch to a separate no-op job | none | dynamic `dependency-graph/compare` HTTP-status preflight |
| trigger | `pull_request: branches: [main, developmental]` | `pull_request` | `pull_request` | `pull_request`, `workflow_dispatch` |
| concurrency group | none | workflow+PR/ref group, cancel-in-progress | none | `dependency-review-`+PR/ref group, cancel-in-progress |
| `actions/checkout` pin | unpinned `@v4` | not used | SHA `3d3c42e5aac5ba805825da76410c181273ba90b1` | SHA `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` (v7.0.0) |
| `dependency-review-action` pin | unpinned `@v4` | SHA `a1d282b36b6f3519aa1f3fc636f609c47dddb294` (v5.0.0) | same SHA | same SHA |

Two decisions this audit drove (see ADR-0024 for the full reasoning):

1. `fail_on_severity`, `allow_ghsas`, and `continue_on_error` stay per-caller
   `workflow_call` inputs — flattening them to one shared value would
   silently loosen mightyETL's `high` gate or newsdom-api's documented GHSA
   allowlist exception.
2. scopeweave's dynamic Dependency Graph availability preflight (an actual
   API capability check) replaces mightyETL's static
   `github.event.repository.private` assumption everywhere, because the
   assumption is provably wrong in both directions (a private+GHAS repo, or
   a public+Dependency-Graph-disabled repo). argos and newsdom-api gain this
   safety net for free; they previously had none.

## Mechanism

`.github/workflows/dependency-review.yml` (this repository) takes three
`workflow_call` inputs (`fail_on_severity`, `allow_ghsas`,
`continue_on_error`) and always runs the checkout → availability-preflight →
conditional dependency-review → conditional unavailability-note sequence.
Each calling repository's own thin `.github/workflows/dependency-review.yml`
keeps that repository's original `on:` trigger block (argos keeps its
`branches: [main, developmental]` restriction — a `workflow_call` target
cannot itself be what GitHub triggers on pull_request), gains a
`concurrency` block if it lacked one, and adds one job:
`uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@main`
with only that repository's non-default `with:` values.

### argos caller

```yaml
name: Dependency Review

on:
  pull_request:
    branches: [main, developmental]

concurrency:
  group: dependency-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@main
    with:
      fail_on_severity: moderate
      continue_on_error: true
```

### mightyETL caller

```yaml
name: Dependency Review

on:
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@main
    with:
      fail_on_severity: high
```

### newsdom-api caller

```yaml
name: dependency-review

on:
  pull_request:

concurrency:
  group: dependency-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@main
    with:
      fail_on_severity: low
      allow_ghsas: "GHSA-69w3-r845-3855"
```

### scopeweave caller

```yaml
name: Dependency Review

on:
  pull_request:
  workflow_dispatch:

concurrency:
  group: dependency-review-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  dependency-review:
    if: github.event_name == 'pull_request'
    uses: ContextualWisdomLab/.github/.github/workflows/dependency-review.yml@main
    with:
      fail_on_severity: low
```

scopeweave's original also supported a `workflow_dispatch` trigger, but its
own dependency-review job only ever ran the gate for `pull_request` events
(the availability check itself early-exited with a "only runs for
pull_request events" note otherwise) — the caller keeps `workflow_dispatch`
in its trigger list for manual runs of other jobs in that repository's
workflow file, if any, but gates this job to `pull_request` to preserve
that exact original behavior; the reusable workflow's own preflight step
still requires `github.event.pull_request.base.sha` / `.head.sha`, which
only exist on a `pull_request` event.

## Verified before merge

- `python3 -c "import yaml; yaml.safe_load(open(...))"` on all five files
  (the reusable workflow and four callers).
- `actionlint` clean on all five files.
- Full `coverage run -m pytest tests` (2626 passed, 1 skipped) plus
  `interrogate` on `ContextualWisdomLab/.github`, confirming the new
  contract test and no regression elsewhere.
