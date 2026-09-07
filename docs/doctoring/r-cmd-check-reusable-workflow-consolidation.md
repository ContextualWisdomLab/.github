# R-CMD-check reusable workflow consolidation

## Current authority

This record describes the Proposed owner change in `ContextualWisdomLab/.github#1716`. Protected `main` remains production authority until the exact candidate integrates. Consumer PRs in `ContextualWisdomLab/kaefa` and `ContextualWisdomLab/nonnest2` must not consume this PR branch or mutable `@main`; after integration they pin the exact protected-main commit that contains the reusable workflow.

## Original duplication

`ContextualWisdomLab/kaefa` and `ContextualWisdomLab/nonnest2` both derived their R-CMD-check workflow from the r-lib Actions examples. Their common sequence and common authority fields justified a canonical reusable owner. Their real differences are bounded data/capabilities: trigger branches, R matrix, TinyTeX requirement, extra R packages, check arguments, and kaefa's one testthat regression.

The action pins selected by the proposal are `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` and `r-lib/actions/*@6f6e5bc62fba3a704f74e7ad7ef7676c5c6a2590`. `permissions: contents: read`, `GITHUB_PAT`, `R_KEEP_PKG_SOURCE`, `build_args`, `error-on`, and snapshot-upload behavior remain owned centrally rather than becoming consumer inputs.

## Security RCA: free-form pre-check shell

The first candidate represented kaefa's two-command regression as a string input named `pre_check_script` and executed it with `run: ${{ inputs.pre_check_script }}`. Devin current-head review identified the resulting security boundary defect: reusable-workflow callers could provide arbitrary Bash source to a central job that receives the caller repository token.

This is a canonical-owner defect, not a finding to suppress or merely document. The repair lineage on 2026-09-02 is:

- RED commit `5e838ab35d062faa488b03ae78f9f8d84447e223`: adds an executable contract forbidding `pre_check_script`/caller-authored `run:` and requiring a bounded test-file data path;
- production commit `931c8f32a2e5e743ca0fbdee3d6728170ff2b273`: removes arbitrary shell input and introduces `install_package_before_pre_check` plus `pre_check_test_file`;
- contract-alignment commit `6ca3080326f3498904d6222c60089e35a050b848`: verifies step order, capability gates, environment-data binding, and fail-closed path checks on the repaired source.

The repaired workflow owns its executable commands. When requested, it runs a fixed package installation command. The optional test file is passed only as `PRE_CHECK_TEST_FILE`, must match repository-relative `tests/testthat/*.R`, and is rejected for parent traversal, absolute-path prefixes, carriage returns, or newlines before the fixed `testthat::test_file(Sys.getenv("PRE_CHECK_TEST_FILE"))` command executes. No consumer string is evaluated as shell source.

## Consumer equivalence

The bounded replacement preserves kaefa's valid behavior without preserving the unsafe representation. Its former commands were:

1. install the current package from source;
2. run `tests/testthat/test-zh-misfit-decision-rule.R` through testthat.

The equivalent bounded caller values are:

- `install_package_before_pre_check: true`;
- `pre_check_test_file: tests/testthat/test-zh-misfit-decision-rule.R`.

Kaefa's five-leg R matrix, `any::rcmdcheck` + `any::testthat`, and `c("--no-manual", "--no-tests")` remain data inputs. Nonnest2 needs no pre-check capability and keeps its own trigger branches/TinyTeX behavior. Each consumer must pin the eventual owner protected-main SHA and regenerate its own current-head evidence.

## Validation contract

`tests/test_r_package_check_reusable_workflow_contract.py` checks the six bounded inputs, optional-step gates, immutable action pins, uniform central fields, matrix binding, absence of free-form shell input, and the fail-closed test-file grammar. Repository-wide pytest/coverage, docstring checks, actionlint, security workflows, and current-head independent review remain merge evidence only when they execute on the unchanged exact current head; predecessor results are historical evidence, not transferable approval.

The unresolved Devin thread on the vulnerable implementation must remain unresolved until exact-head evidence proves the repaired successor. Queue saturation is not authority to bypass this substantive security finding.

## Context and standards

Reusable workflows establish an execution boundary: GitHub explicitly documents that called workflows receive permissions constrained by the caller and that permissions cannot be elevated through the call chain. This repair additionally minimizes the command surface so caller-controlled values remain data rather than command text. Shell/path validation here is defense in depth; the primary design rule is that the workflow itself owns executable source.

## References (APA 7th edition)

GitHub, Inc. (n.d.). *Reusing workflows*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows

GitHub, Inc. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

r-lib. (n.d.). *actions: GitHub Actions for the R community* [Computer software]. GitHub. Retrieved September 2, 2026, from https://github.com/r-lib/actions/tree/v2/examples
