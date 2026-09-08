# Host-scoped Actions inventory credentials

Decision date: **2026-09-07**

## Problem

The central scheduler reads and cancels workflow runs in two authority domains.
Runs hosted by `ContextualWisdomLab/.github` are visible to the receiving
workflow's runner token. Runs hosted by a target repository require the explicit
cross-repository Actions credential. Sending both through the mutation App
couples current-head admission to that installation's independent rate-limit
bucket and reproduces the queue blocker recorded in
[ContextualWisdomLab/.github#1231](https://github.com/ContextualWisdomLab/.github/pull/1231).

## Decision

Select the credential from the repository that hosts the run. Repository
identity is compared case-insensitively. Central inventory and cancellation use
the configured dispatch/runner token; all target repositories continue through
the explicit Actions token. Missing credentials continue to fail at the GitHub
API boundary—there is no paid, anonymous, or mutable-head fallback.

## Failure scenes

- If the mutation App quota is exhausted, central current-head discovery still
  uses the runner token and can release stale central runs.
- If a target repository is queried, the scheduler never substitutes the
  central runner token, whose scope is insufficient.
- If repository casing differs, the same central repository is not
  misclassified as a target.

## Evidence and follow-up

The permanent regression first appears at RED commit
`8cc62ce8837e456dfac4f592bcbd0786a77e4b81`. The implementation must receive
fresh exact-head GitHub Checks before the PR can leave Proposed status.

## References

GitHub. (2026). *REST API endpoints for workflow runs*.
https://docs.github.com/en/rest/actions/workflow-runs

GitHub. (2026). *Automatic token authentication*.
https://docs.github.com/actions/security-for-github-actions/security-guides/automatic-token-authentication
