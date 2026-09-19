# CodeQL required workflow denies private consumers a read they need — 2026-09-13

## Symptom

Private consumer `ContextualWisdomLab/late-life-anxiety-reanalysis` PR #10 (head `a1cd5bc6783c6510dfcf937f523c733366e82213`, run `34700410434`) failed both org-required `.github/workflows/codeql-pr.yml` jobs at their first API call, each with `gh: Resource not accessible by integration (HTTP 403)`. `CodeQL compatibility analysis (python)` (job `103571590442`), step "Read current-head CodeQL dispatch verdict", calls `gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"` under `GH_TOKEN: ${{ github.token }}`; the runner printed effective token permissions of Contents: read, Metadata: read only (declared: `contents: read`, `id-token: write`). `Dispatch current-head CodeQL scan` (job `103571810868`) makes the same GET, then later reads `repos/${TARGET_REPOSITORY}/commits/${PR_HEAD_SHA}/statuses`, under `contents: read`, `id-token: write`, `actions: read`. Public consumers (fast-mlsirm, pg-erd-cloud, naruon, html4tree) pass the identical workflow only because GET on a *public* repository needs no fine-grained grant; the defect is specific to private repositories.

## Root cause

Neither job declared the fine-grained read permissions GitHub's REST contract requires for these calls on a private repository: "Get a pull request" needs `pull-requests: read`; "List commit statuses for a reference" needs `statuses: read`. Missing both, the minted `GITHUB_TOKEN` had no read access to pull-request or status data on a private repo, and testing against public consumers never exercised the gap because anonymous-equivalent GETs on public repository resources are always permitted.

## Repair

Added `pull-requests: read` and `statuses: read` to the `analyze-head` and `dispatch-current-head` job `permissions:` blocks in `.github/workflows/codeql-pr.yml`, preserving declaration order (contents, id-token, [actions], pull-requests, statuses). No write permission is added anywhere; `actions: write` remains absent, still guarded by the existing `test_codeql_required_workflow_does_not_gain_actions_write` regression test.

## Local evidence

New test `test_codeql_pr_jobs_hold_read_grants_private_consumers_need` in `tests/test_codeql_pr_workflow_contract.py` slices both permission blocks the same way the neighboring `actions: write` guard does and asserts each holds exactly `pull-requests: read` and `statuses: read` with no `actions: write`. RED: 1 failed (`assert [] == ['read']`). GREEN: 1 passed. Combined focused run across the five CodeQL/required-workflow contract test files: 149 passed. Full repository suite and `actionlint` result are recorded in the pull request description.

## Hosted acceptance still required

This repair is unverified against GitHub's live permission enforcement. A newly loaded central SHA carrying this change must still pass both `analyze-head` and `dispatch-current-head` on the private consumer's exact current head before the defect is resolved end-to-end. Separately, the later `repository_dispatch` POST from `dispatch-current-head` to `ContextualWisdomLab/.github` using the OpenCode app token has not yet been exercised from a private consumer at all, and may surface a distinct scoping issue of its own once this read-permission blocker is cleared.

## References

- GitHub REST, "Get a pull request": https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request (fine-grained permission: `pull-requests: read`)
- GitHub REST, "List commit statuses for a reference": https://docs.github.com/en/rest/commits/statuses#list-commit-statuses-for-a-reference (fine-grained permission: `statuses: read`)
