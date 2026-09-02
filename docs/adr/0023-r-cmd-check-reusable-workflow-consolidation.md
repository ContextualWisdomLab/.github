# ADR-0023: Consolidate kaefa/nonnest2 R-CMD-check.yaml into one reusable workflow

- **Status:** Accepted
- **Date:** 2026-09-02
- **Scope:** ContextualWisdomLab/.github `.github/workflows/` (new reusable workflow);
  ContextualWisdomLab/kaefa and ContextualWisdomLab/nonnest2 `.github/workflows/R-CMD-check.yaml`
  (each replaced by a thin `workflow_call` caller)

## Context

kaefa and nonnest2 each carry a hand-copied `R-CMD-check.yaml`, both generated
from the same upstream r-lib template
(https://github.com/r-lib/actions/tree/v2/examples): both open with the
identical "Workflow derived from..." header, and both run the identical
`actions/checkout` -> `r-lib/actions/setup-pandoc` -> `r-lib/actions/setup-r`
-> `r-lib/actions/setup-r-dependencies` -> `r-lib/actions/check-r-package`
step sequence with the same `GITHUB_PAT` / `R_KEEP_PKG_SOURCE` env vars and
the same `permissions: contents: read`. This is the same pattern
ADR-0021 named for the hourly review-repair callers: near-duplicated
GitHub Actions YAML that differs only in the fields a `workflow_call` input
was built to carry.

Reading both files in full (not just the survey that proposed this
consolidation) surfaced two genuinely varying fields the survey had not
named -- `docs/doctoring/r-cmd-check-reusable-workflow-consolidation.md`
records the full field-by-field audit, including these:

- kaefa's `setup-r-dependencies` installs `any::rcmdcheck` **and**
  `any::testthat` (its own regression-test step needs `testthat`);
  nonnest2 installs only `any::rcmdcheck`.
- kaefa's `check-r-package` overrides `args: 'c("--no-manual", "--no-tests")'`
  (it already ran its package's tests via the regression-test step, so
  `R CMD check` itself skips re-running them); nonnest2 omits `args:`
  entirely, taking `check-r-package`'s own upstream default,
  `c("--no-manual", "--as-cran")`.

Neither is the kind of difference a survey summary line ("same step
sequence") would show without opening both action's `with:` blocks.
Both are exactly the kind of field a `workflow_call` input handles, so
they do not change the Decision below -- but they are new inputs beyond the
ones the initial proposal named, and are called out here per this
repository's standing convention of not forcing a consolidation past
genuine per-repo variance without naming it (see `docs/CWL-MASTER-CONTEXT.md`
§7 and the precedent this ADR follows, ADR-0021).

`docs/product-technical-gap-baseline.md` gap-baseline snapshot and IRT-bibliography-set
(named as a plausible third target) returned 404 for a `.github/workflows`
directory during the survey -- it has no CI workflow of this shape yet, so it
is not a target of this change; the reusable workflow is still built openly
so a future R package repo can adopt it without a new ADR.

## Decision

1. One new reusable workflow, `.github/workflows/r-package-check.yml` in
   this repository, implements the shared r-lib check sequence behind
   `workflow_call` inputs:
   - `r_matrix` (JSON string, default a single `ubuntu-latest`/`release`
     leg) -- becomes `strategy.matrix.config` via `fromJSON()`.
   - `needs_tinytex` (boolean, default `false`) -- gates an optional
     `r-lib/actions/setup-tinytex` step (nonnest2's PDF vignette needs it;
     kaefa does not use it).
   - `extra_packages` (string, default `any::rcmdcheck`) -- forwarded to
     `setup-r-dependencies`'s `extra-packages` input.
   - `check_args` (string, default `c("--no-manual", "--as-cran")`,
     matching `check-r-package`'s own upstream default so nonnest2's
     behavior is unchanged by omission-turned-explicit) -- forwarded to
     `check-r-package`'s `args` input.
   - `pre_check_script` (string, default empty -- step skipped) -- an
     optional shell step run between dependency setup and the check step,
     for kaefa's package-install-then-`testthat::test_file()` regression
     check.
2. `GITHUB_PAT: ${{ secrets.GITHUB_TOKEN }}`, `R_KEEP_PKG_SOURCE: yes`,
   `permissions: contents: read`, `build_args: 'c("--no-manual")'`,
   `error-on: '"error"'`, and `upload-snapshots: true` were uniform across
   both originals and are hardcoded in the reusable workflow, not exposed
   as inputs.
3. The `on: push` / `on: pull_request` trigger (and each repository's own
   branch list) stays in each calling repository's own thin
   `.github/workflows/R-CMD-check.yaml` -- a `workflow_call` target cannot
   itself be the workflow GitHub triggers directly on push/PR, so this
   cannot move into the reusable file. kaefa keeps
   `[main, master, develop]`; nonnest2 keeps `[main, master]` -- these were
   already different before this change and are preserved exactly.
4. Each repository's local file collapses to a thin caller: `on:` (its
   existing trigger config, untouched) plus one job,
   `uses: ContextualWisdomLab/.github/.github/workflows/r-package-check.yml@main`,
   with only that repository's actual non-default `with:` values --
   nonnest2's caller sets only `needs_tinytex: true`; kaefa's sets
   `r_matrix`, `extra_packages`, `check_args`, and `pre_check_script`
   (all four differ from the reusable workflow's defaults). This follows
   the exact `@main`-reference convention `deploy-pages.yml` already
   documents for this repository's other reusable workflows.
5. Action version pins are unified to this repository's own current pins
   rather than parameterized: `actions/checkout` moves to
   `3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1` (kaefa's existing
   pin; nonnest2 was on the older `v6.0.2`), and every `r-lib/actions/*`
   step moves to `6f6e5bc62fba3a704f74e7ad7ef7676c5c6a2590 # v2` (nonnest2's
   existing uniform pin for all of its r-lib steps, and already the pin
   kaefa used for three of its four r-lib steps). This is a routine
   version-pin bump of the kind Dependabot performs, not a parameterized
   per-repo field: no `workflow_call` input exists for "which SHA," and
   both repositories converge on whichever pin was already newest/more
   uniform in this ecosystem.

## Consequences

- Adding a third R package repository (e.g. a future IRT-bibliography-set)
  to this pattern is a ~15-line caller file with only its own differing
  `with:` values, not a copy-pasted 30+-line workflow.
- kaefa's `setup-pandoc` step, previously pinned to a stray SHA
  (`d3c5be51b12e724e68f33216ca3c148b66d5f0b6 # v2`) different from its own
  other three r-lib steps -- an inconsistency *within* kaefa's own prior
  file, not a genuine cross-repo difference -- now uses the same pin as
  every other r-lib step in both repositories, closing that drift as a
  side effect of consolidation (same category of incidental fix ADR-0021
  made for Clearfolio's missing job permissions).
- nonnest2's `actions/checkout` pin moves from `v6.0.2` to `v7.0.1` as part
  of adopting the shared workflow; `docs/doctoring/r-cmd-check-reusable-workflow-consolidation.md`
  records that this is the only originally-unpinned-to-kaefa's-version
  action bump this change makes, and that it is a well-tested checkout
  action major-version-stable bump, not a behavioral change to the R check
  itself.
- Neither kaefa's `develop` branch nor nonnest2's `master` branch has GitHub
  branch protection configured (`gh api .../branches/.../protection` -> 404
  for both, verified before writing this ADR), so there is no required
  status-check name this change could silently break by changing how the
  matrix job's check name is composed.

## Rejected alternatives

- **A single shared file with no inputs, hardcoding kaefa's 5-leg matrix
  and regression step for both repos.** Rejected: nonnest2 has no
  `testthat`-based regression suite step and does not build with a PDF
  vignette toolchain matrix; forcing kaefa's shape onto it would run steps
  that reference files nonnest2 does not have.
- **Parameterize the action version pins as `workflow_call` inputs.**
  Rejected: pin choice is a security/supply-chain decision belonging to
  the reusable workflow's own maintainers, not a per-repo product
  difference; unifying to one current pin (as this repository already
  does for `actions/checkout` in `deploy-pages.yml`,
  `pr-review-fix-scheduler.yml`, and 40+ other in-repo workflows) keeps a
  single place to bump it later.
- **Leave `check_args` unset by default and require every caller to pass
  it explicitly.** Rejected: nonnest2's original file never set `args:`
  at all, so defaulting to `check-r-package`'s own upstream default
  reproduces nonnest2's exact prior behavior with zero `with:` lines,
  rather than forcing every future caller to memorize and repeat
  `check-r-package`'s own default.
