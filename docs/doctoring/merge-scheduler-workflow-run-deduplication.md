# Central merge-scheduler `workflow_run` deduplication

검토 기준일: **2026-08-21**

## Incident

The central `Required PR Review Merge Scheduler` accumulated several queued
`workflow_run` executions with the same default-branch `head_sha` and no PR
metadata. These runs were redundant repository-wide scans. The existing
current-head cleanup handled pull-request, push, and schedule runs, but did
not classify this metadata-free `workflow_run` shape. The same event also used
the default concurrency fallback without `cancel-in-progress`, so later runs
did not remove an older queued scan.

## Decision

1. Include `workflow_run` in the scheduler's existing conditional
   `cancel-in-progress` expression. PR-associated workflow-run events retain
   their PR-specific concurrency key; metadata-free events use the existing
   default-branch fallback.
2. During the organization sweep, inspect only runs named exactly
   `Required PR Review Merge Scheduler` with event `workflow_run`, the current
   default branch, an empty `pull_requests` list, and complete Actions-run
   evidence.
3. Restrict the dedupe to the exact current default-branch `head_sha`, then
   sort by creation time and run ID. Keep the newest run and cancel older
   same-head runs. If the current default SHA is absent, skip this additional
   cancellation path; older-head cleanup remains governed by the existing
   stale-run policy.
4. Preserve the existing fail-closed behavior: incomplete PR-head, default
   branch, or Actions-run reads disable queue cancellation for that repository.

This is queue hygiene only. It does not reinterpret a check, publish a status,
approve a pull request, alter branch protection, or merge a branch.

## Verification and rollback

The contract test proves the exact workflow trigger, workflow identity,
metadata boundary, same-head selection, and deterministic ordering. The extracted jq
program was also run against a fixture containing duplicate same-head runs,
an older-head run, a PR-associated run, and an unrelated workflow; it selected
only the older duplicate. `actionlint`, `git diff
--check`, and the focused pytest passed on the change branch.

Rollback reverts the workflow concurrency expression, the additional queue
hygiene block, the focused contract test, and these documentation entries in
one normal pull request. No GitHub Actions registry state is mutated by the
code change itself.

## References

GitHub. (2026). *Control the concurrency of workflows and jobs*. GitHub Docs.
https://docs.github.com/en/enterprise-cloud@latest/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

GitHub. (2026). *Events that trigger workflows: `workflow_run`*. GitHub Docs.
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (2026). *Managing workflow runs*. GitHub Docs.
https://docs.github.com/en/actions/how-tos/manage-workflow-runs
