# PR-stable workflow concurrency contract

Status: proposed regression guard. Gap: G-03.

## Problem

The existing queue-contract suite checks that a PR number appears in a workflow, but that alone does not prove the actual workflow-level `concurrency.group` includes the PR number. A regression could leave the number in a comment or job condition while making the group repository-wide. Different PRs could then cancel or replace each other's runs.

Protected source observed at `main@7554587c2e3106a388998bcad048a3d7121de25e`:

- `codeql-pr.yml` blob `356244f7fcba9088744d4bf212b2a3470cbacd86`
- `noema-review.yml` blob `08ea60053805df66a4139267ab3a149790438bed`
- `opencode-review.yml` blob `1194d7eea6c5af958a27a2419209a086791f4d66`
- `security-scan.yml` blob `e04d7bf8f3d6078f1eba213f58fc21d256b21c32`

## Decision

Add `tests/test_pr_stable_concurrency_contract.py` as a separate test module to avoid editing the high-contention queue-contract file. The new contract reads only the actual workflow-level group scalar, excludes comments and sibling settings, and asserts repository identity, PR number, and absence of head SHA for all four workflows. A parser fixture proves a comment cannot satisfy the assertion.

No workflow source or runtime behavior changes. Existing tests remain responsible for synchronize triggers, live-head admission, and cleanup behavior.

## Validation and risks

A local parser probe against the four current group shapes passed 4/4; replacing the PR-number expression with a run-ID expression is rejected. Full repository tests, fresh exact-head hosted Checks, and qualifying independent review remain required before merge. If a future workflow deliberately uses another stable identity, document that exception and update this contract rather than weakening it globally.

Operationally, PR A's new head may supersede PR A's old run, but it must not cancel PR B's run in the same repository.
