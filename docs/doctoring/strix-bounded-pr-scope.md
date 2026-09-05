# Strix bounded pull-request scope and CI recursion contract

## Purpose

This doctoring record defines the trusted boundary used when Strix reviews a bounded set of pull-request changes from an organization-required workflow. It also records the GitHub Actions recursion behavior encountered while repairing the boundary so that future maintainers do not misclassify infrastructure state as a target-code defect.

## Incident chain

A downstream OpenCode review dispatch for `ContextualWisdomLab/pg-llm-batch#190` failed while the central workflow materialized its trusted `uv` executable. The trusted download retained a fixed Astral release URL, a no-proxy/no-redirect opener, a bounded response read, SHA-256 verification, and executable-version verification, but the request did not identify the organization client. Pull request #939 adds a fixed `User-Agent` and regression coverage without weakening those trust checks.

During verification of the central repair, Strix received an intentionally bounded pull-request target. The GitHub Actions runner created that target below a host temporary directory, while the Strix sandbox mounted the same files below `/workspace/<workspace_subdir>`. The original host path was intentionally absent inside the sandbox. Treating that absence as a missing-code vulnerability was therefore a scanner-orientation error, not a finding in the pull-request content.

Repair workflow run `31784776654` established the regression test first, applied the trusted static scope guidance, ran shell syntax validation, ran the focused Python contract, and completed the full `scripts/ci/test_strix_quick_gate.sh` harness before committing the production change. Both temporary repair workflows were removed by the verified commit.

## Trusted scope contract

The following invariants apply:

1. `pull_request_target` executes the protected-base workflow and trusted gate implementation. Pull-request content is materialized as data in a separate bounded directory; it is not executed with privileged credentials.
2. A target created under the runner host temporary directory may be mounted at `/workspace/<workspace_subdir>` inside the Strix sandbox. Absence of the original host pathname inside the sandbox is expected.
3. For the internal bounded pull-request scope only, the trusted gate supplies a static instruction explaining the mount contract and directing Strix to inspect the files present in the current working directory.
4. No repository input, dispatch payload, pull-request field, environment override, or caller-supplied instruction is forwarded to the security model. The instruction is selected only when `TARGET_PATH_IS_INTERNAL_PR_SCOPE=1` was set by trusted scope materialization.
5. The bounded directory is the complete authorized target for the changed-path scan. Strix must continue to report actionable vulnerabilities in the workflow, shell, Python, configuration, and other eligible files that are actually present.
6. Scope orientation must not suppress provider failures, malformed reports, integrity failures, missing authorized files, or vulnerabilities in present content. Those conditions remain fail-closed.

## GitHub Actions recursion behavior

The verified repair commit was pushed by a workflow using the repository `GITHUB_TOKEN`. GitHub created the resulting pull-request workflow runs in an approval-required state and reported `action_required` without jobs. This is GitHub's recursion protection rather than test execution evidence. A maintainer-authenticated commit or explicit workflow approval is required before exact-head CI can run normally.

This repository must not replace the recursion protection with a broadly privileged token merely to make a self-repair workflow recursively trigger CI. Temporary repair workflows must remain narrowly scoped, use least-privilege `contents: write`, verify that the remote branch has not advanced, run the full regression harness before pushing, and delete themselves from the resulting production commit.

## Regression evidence

The minimum local or CI evidence for this boundary is:

```bash
bash -n scripts/ci/strix_quick_gate.sh
python3 -m unittest discover \
  --start-directory tests \
  --pattern 'test_strix_internal_scope_instruction_contract.py' \
  --verbose
bash scripts/ci/test_strix_quick_gate.sh
```

The exact pull-request head must additionally complete the trusted-uv materializer quality workflow, Strix changed-path quality workflow, repository security workflows, required OpenCode review, required Strix scan, and all protected-branch review requirements. A previous-head repair run, an approval-required run with no jobs, or a downstream repository's successful leaf checks cannot substitute for current-head central evidence.

## Operational recovery sequence

1. Confirm the downstream source head and reproduce the central failure against that exact SHA.
2. Repair the central trusted implementation; do not add unrelated downstream source changes.
3. Add a regression contract that fails before the central repair and passes after it.
4. Verify trusted URL, redirect, proxy, size, checksum, executable-version, and credential boundaries remain intact.
5. Run the full Strix gate harness before committing a scope-orientation change.
6. Remove temporary repair automation from the production diff.
7. Obtain exact-head central CI and independent approvals without dismissing reviews or bypassing branch protection.
8. Merge the central repair normally, then rerun the downstream review on the unchanged downstream head so the infrastructure-derived review is superseded through the standard review path.

## References

GitHub. (n.d.). *GITHUB_TOKEN*. GitHub Docs. Retrieved August 14, 2026, from https://docs.github.com/en/actions/concepts/security/github_token

GitHub. (n.d.). *Securely using pull_request_target*. GitHub Docs. Retrieved August 14, 2026, from https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
