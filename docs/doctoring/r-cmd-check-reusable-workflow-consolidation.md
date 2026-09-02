# R-CMD-check reusable workflow consolidation

## Decision

kaefa's and nonnest2's `.github/workflows/R-CMD-check.yaml` files -- both
auto-generated from the same upstream r-lib template
(https://github.com/r-lib/actions/tree/v2/examples) -- are replaced by one
new reusable workflow, `.github/workflows/r-package-check.yml` in this
repository, plus a thin `workflow_call` caller left in place of each
repository's own `R-CMD-check.yaml`. See
[ADR-0023](../adr/0023-r-cmd-check-reusable-workflow-consolidation.md).

Both original files opened with the same "Workflow derived from..." header
comment and ran the same `actions/checkout` -> `setup-pandoc` -> `setup-r`
-> `setup-r-dependencies` -> `check-r-package` sequence, with the same
`GITHUB_PAT` / `R_KEEP_PKG_SOURCE` env vars and the same
`permissions: contents: read`. A third named candidate,
IRT-bibliography-set, returned 404 for a `.github/workflows` directory
during the survey (`gh api repos/ContextualWisdomLab/IRT-bibliography-set/contents/.github/workflows`)
-- it has no workflow of this shape today, so it is not a target of this
change.

## Mechanism

`.github/workflows/r-package-check.yml` takes five `workflow_call` inputs
(`r_matrix`, `needs_tinytex`, `extra_packages`, `check_args`,
`pre_check_script`) and runs the fixed r-lib step sequence once per
`strategy.matrix.config` entry from `fromJSON(inputs.r_matrix)`. Each
calling repository's own `.github/workflows/R-CMD-check.yaml` keeps its
existing `on: push` / `on: pull_request` trigger block (untouched -- a
`workflow_call` target cannot itself be what GitHub triggers on push/PR)
and adds one job that does
`uses: ContextualWisdomLab/.github/.github/workflows/r-package-check.yml@main`
with only that repository's non-default `with:` values.

## Non-uniform fields found while auditing

Reading both files' full `with:` blocks (not just the header comment and
step-name sequence the initial survey compared) found:

- **`on.push`/`on.pull_request` branches.** kaefa:
  `[main, master, develop]`; nonnest2: `[main, master]`. Different, and
  already different before this change -- preserved exactly in each
  repository's own caller, since this lives in the trigger block that
  cannot move into the reusable file at all.
- **`actions/checkout` pin.** kaefa:
  `3d3c42e5aac5ba805825da76410c181273ba90b1` (`v7.0.1`); nonnest2:
  `de0fac2e4500dabe0009e67214ff5f5447ce83dd` (`v6.0.2`). Not called out in
  the initial survey. Resolved by unifying to kaefa's newer pin
  (`v7.0.1`), which is already this repository's own current pin for
  `actions/checkout` in its most recently touched workflows
  (`pr-review-fix-scheduler.yml`, `agent-mention-router.yml`,
  `agent-mention-router-quality-ci.yml`,
  `opencode-rust-coverage-toolchain-quality-ci.yml`) -- a routine version
  bump, not a per-repo parameter, since no functional difference between
  checkout v6 and v7 affects an R package check.
- **`r-lib/actions/*` pins.** nonnest2 pins every one of its r-lib steps
  (`setup-pandoc`, `setup-tinytex`, `setup-r`, `setup-r-dependencies`,
  `check-r-package`) to `6f6e5bc62fba3a704f74e7ad7ef7676c5c6a2590`. kaefa
  pins three of its four r-lib steps (`setup-r`, `setup-r-dependencies`,
  `check-r-package`) to that same SHA, but its `setup-pandoc` step was
  pinned to a *different* SHA, `d3c5be51b12e724e68f33216ca3c148b66d5f0b6`
  -- an inconsistency inside kaefa's own file, not a genuine cross-repo
  difference (nothing in kaefa's history or comments explains a deliberate
  pandoc-specific pin; it reads as unnoticed drift, the same category of
  finding as ADR-0021's Clearfolio permissions gap). The reusable
  workflow uses `6f6e5bc62fba3a704f74e7ad7ef7676c5c6a2590` for every
  r-lib step, uniformly, which is what 4 of kaefa's and nonnest2's
  combined 9 r-lib step pins already used -- silently closing that one
  stray pin as a side effect of consolidation.
- **`setup-r-dependencies`'s `extra-packages`.** kaefa:
  `any::rcmdcheck` **and** `any::testthat` (needed by its own
  regression-test step, which calls `testthat::test_file()` directly).
  nonnest2: `any::rcmdcheck` only. **Not named in the initial survey**,
  which described both as `extra-packages: any::rcmdcheck`. Found only by
  reading kaefa's full `with:` block, not just its step names. Carried as
  the new `extra_packages` input, defaulting to `any::rcmdcheck` (so
  nonnest2's caller needs no `with:` line for it at all) with kaefa's
  caller passing both packages via a block-scalar string identical in
  content to kaefa's original YAML.
- **`check-r-package`'s `args`.** kaefa passes
  `args: 'c("--no-manual", "--no-tests")'` explicitly (it already ran its
  package's tests via the regression-test step, so `R CMD check` itself
  skips re-running them). nonnest2 does not set `args:` at all, which
  means it took `check-r-package`'s own upstream default,
  `c("--no-manual", "--as-cran")` (verified by reading
  `r-lib/actions@6f6e5bc62fba3a704f74e7ad7ef7676c5c6a2590`'s
  `check-r-package/action.yaml` directly rather than assuming). **Not
  named in the initial survey at all.** Carried as the new `check_args`
  input, defaulting to that exact upstream default string so nonnest2's
  caller reproduces its prior (implicit) behavior byte-for-byte with no
  `with:` line, while kaefa's caller passes its override explicitly.
- **kaefa's regression-test step.** Not a single Rscript path as the
  initial proposal suggested, but two separate `Rscript -e` invocations in
  one `run:` block: `install.packages(".", repos = NULL, type = "source")`
  then `library(kaefa); testthat::test_file("tests/testthat/test-zh-misfit-decision-rule.R")`.
  Carried through unmodified as the multi-line `pre_check_script` input
  value (a shell `run:` block, not a single script-file path), which
  reproduces the original two-command sequence exactly. The reusable
  workflow gives this step a fixed, generic name,
  "Run pre-check script (repo-specific)", losing kaefa's original
  step-name ("Run Zh formula regression tests"); this is a deliberate,
  cosmetic simplification for a two-repo abstraction, not a behavior
  change -- see Non-goals.
- `GITHUB_PAT: ${{ secrets.GITHUB_TOKEN }}`, `R_KEEP_PKG_SOURCE: yes`,
  `permissions: contents: read`, `build_args: 'c("--no-manual")'`,
  `error-on: '"error"'`, and `upload-snapshots: true` were byte-identical
  across both files and are hardcoded in the reusable workflow rather than
  exposed as inputs, since there is nothing to look up.

## Verification

- `actionlint .github/workflows/r-package-check.yml` passes (run from this
  repository's root).
- `actionlint` also passes on both product repositories' new caller files,
  run against local copies of the exact content pushed to each PR branch,
  before pushing.
- `tests/test_r_package_check_reusable_workflow_contract.py` reads
  `.github/workflows/r-package-check.yml` as text and asserts: all five
  `workflow_call` inputs exist with the defaults recorded above; the step
  order (checkout, setup-pandoc, conditional setup-tinytex, setup-r,
  setup-r-dependencies, conditional pre-check step, check-r-package); the
  `r-lib/actions/*` pins are uniformly
  `6f6e5bc62fba3a704f74e7ad7ef7676c5c6a2590`; the `actions/checkout` pin is
  `3d3c42e5aac5ba805825da76410c181273ba90b1`; `permissions: contents: read`
  at the workflow level; and that the uniform, non-parameterized fields
  (`R_KEEP_PKG_SOURCE`, `build_args`, `error-on`, `upload-snapshots`) are
  present with their exact original values.
- Branch protection was checked directly for both repositories before
  writing this record:
  `gh api repos/ContextualWisdomLab/kaefa/branches/develop/protection` and
  `gh api repos/ContextualWisdomLab/nonnest2/branches/master/protection`
  both return `404 Branch not protected`, so there is no required
  status-check name this consolidation could silently break by changing
  how GitHub composes the matrix job's check name (a reusable-workflow
  matrix job's check context is `<caller job id> / <inner job name>`,
  which was not previously true for nonnest2's un-matrixed single job).

## Non-goals

- The generic pre-check step name ("Run pre-check script (repo-specific)")
  does not attempt to carry a per-caller custom step label. Only one of
  the two repositories uses `pre_check_script` today; a
  `pre_check_step_name` input can be added if and when a second caller
  needs a distinct label, rather than speculatively adding it now for a
  cosmetic-only difference.
- `docs/product-technical-gap-baseline.md` is a live per-PR gap-tracking
  ledger, not a description of current architecture; this internal CI
  consolidation does not add a new tracked product gap, so no row was
  added there (same reasoning ADR-0021's doctoring record gave).
- IRT-bibliography-set is not added as a third caller: it has no
  `.github/workflows` directory today (`404` on
  `contents/.github/workflows`), so there is nothing in it to migrate.
  The reusable workflow's inputs are general enough to absorb it (or any
  future R package repo in the org) without a new ADR when it exists.
- No new Python was added to `scripts/ci/`, so this change does not touch
  the 100%-coverage / 100%-docstring gates on that directory.

## References (APA 7th edition)

r-lib. (n.d.). *actions: GitHub Actions for the R community* [Computer
software]. GitHub. Retrieved 2026-09-02, from
https://github.com/r-lib/actions/tree/v2/examples

GitHub, Inc. (n.d.). *Reusing workflows*. GitHub Docs. Retrieved
2026-09-02, from
https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
