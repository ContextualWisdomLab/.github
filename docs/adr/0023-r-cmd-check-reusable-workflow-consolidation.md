# ADR-0023: Consolidate kaefa/nonnest2 R-CMD-check.yaml into one reusable workflow

- **Status:** Proposed
- **Date:** 2026-09-02
- **Scope:** `ContextualWisdomLab/.github` reusable R package CI; consumers `ContextualWisdomLab/kaefa` and `ContextualWisdomLab/nonnest2`

## Problem

`ContextualWisdomLab/kaefa` and `ContextualWisdomLab/nonnest2` carry near-identical R-CMD-check workflows derived from the r-lib Actions examples. The shared sequence is checkout → Pandoc → optional TinyTeX → R setup → dependency setup → optional repository-specific regression → `check-r-package`. Copying that sequence creates action-pin, permission, and behavior drift.

A first reusable-workflow implementation exposed the repository-specific regression as a free-form `pre_check_script` string and interpolated it directly into `run:`. Current-head security review correctly identified that design as a privileged-code boundary defect: a reusable caller could supply arbitrary shell source to a job that receives the caller repository token. Consolidation does not justify transferring executable authority from a consumer into a centrally trusted workflow.

## Decision

1. `ContextualWisdomLab/.github/.github/workflows/r-package-check.yml` is the canonical reusable owner for the shared R-CMD-check sequence.
2. The reusable interface is data/capability oriented, not shell oriented. It accepts:
   - `r_matrix`: JSON strategy matrix;
   - `needs_tinytex`: boolean capability;
   - `extra_packages`: dependency input forwarded to r-lib Actions;
   - `check_args`: R CMD check arguments;
   - `install_package_before_pre_check`: boolean capability for the known kaefa regression shape;
   - `pre_check_test_file`: repository-relative `tests/testthat/*.R` path passed as data.
3. Free-form `pre_check_script` is forbidden. The workflow owns the only executable pre-check commands: an optional fixed `install.packages(".", ...)` invocation and a fixed `testthat::test_file(Sys.getenv("PRE_CHECK_TEST_FILE"))` invocation.
4. `pre_check_test_file` fails closed unless it is a relative `tests/testthat/*.R` path and contains no parent traversal, absolute-path prefix, carriage return, or newline. The path enters the shell only through an environment variable; it is never evaluated as shell source.
5. Uniform security/supply-chain fields remain centrally owned and non-parameterized: `permissions: contents: read`, `GITHUB_PAT`, `R_KEEP_PKG_SOURCE`, `build_args`, `error-on`, upload behavior, and immutable action SHAs.
6. Consumer trigger branches remain in each repository's thin caller. Consumers must pin `uses:` to the immutable protected-main commit containing the reusable workflow; mutable `@main`, PR heads, and branch URLs are not production dependency authority.
7. The current proposal remains **Proposed** until this exact candidate passes repository tests/security/review and integrates through protected `main`. Only then may consumer PRs pin the resulting protected-main SHA and reacquire their own exact-head evidence.

## Alternatives considered

- **Keep copied workflows.** Rejected because two already-identical control surfaces drift independently and duplicate maintenance/security review.
- **Free-form shell input.** Rejected because it turns caller data into executable commands in a centrally trusted job.
- **Parameterize action SHAs or permissions.** Rejected because supply-chain and token authority belong to the reusable workflow owner, not individual consumers.
- **Hard-code kaefa-specific file names centrally.** Rejected because the reusable owner should expose the minimum bounded semantic input needed by multiple products, not own product test identity.
- **Consume an unreleased PR-head version from product callers.** Rejected because consumers may use only protected/released immutable owner contracts.

## Invariants and failure scenarios

- A malicious or compromised caller cannot make the central job execute arbitrary Bash through an input.
- An invalid test-file path fails before R execution.
- A caller cannot elevate token permissions through the reusable workflow.
- If protected-main publication has not occurred, consumer adoption remains blocked rather than falling back to a mutable ref.
- Changing the caller to a reusable job may change the published check-context name; consumer branch/ruleset requirements must be re-read before adoption and repaired at the owning ruleset rather than silently weakening protection.

## Consequences and follow-up

The central workflow becomes a small reusable CI contract while product repositories retain only triggers and bounded product-specific values. `ContextualWisdomLab/kaefa#84` must replace its former shell input with `install_package_before_pre_check: true` and `pre_check_test_file: tests/testthat/test-zh-misfit-decision-rule.R`, then pin the eventual protected-main SHA. `ContextualWisdomLab/nonnest2#119` must likewise pin the protected-main SHA. Both consumer PRs remain non-authoritative until the owner integrates and their own current-head gates pass.

The executable regression in `tests/test_r_package_check_reusable_workflow_contract.py` permanently forbids reintroducing caller-authored shell source and verifies the bounded pre-check path.
