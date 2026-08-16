# Manual Strix `workflow_dispatch` is not merge evidence

검토 기준일: **2026-08-16**

## Incident

The merge scheduler treated every `Strix Security Scan` / `strix` check run as
required current-head evidence. A caller-selected `workflow_dispatch` run
publishes that same check name. Official Deep mode can occupy the GitHub-hosted
360-minute ceiling. An in-progress or failed Deep job on a pull-request head
therefore parked `strix_evidence_state()`, could replace a later
`failed_status_checks()` winner for the same workflow/name key, and could
suppress `repository_dispatch` `strix-scan` retry when the scheduler was not in
centralized-dispatch mode.

GitHub's Actions UI and `gh workflow run --ref` let a writer choose the
workflow revision (GitHub, n.d.-a). That revision supplies the workflow
definition before any trusted-source checkout. Manual Deep remains a reviewer
tool, not a merge gate.

## Decision

Required Strix merge evidence is only:

- `pull_request_target` check runs, and
- `repository_dispatch` type `strix-scan` check runs.

The scheduler now:

1. reads `checkSuite.workflowRun.event` on each check run;
2. ignores `workflow_dispatch` check runs in `is_strix_context`,
   `strix_evidence_state`, `failed_status_checks`, `action_required_checks`,
   and `matching_actions_job_id`;
3. treats a completed required Strix check run as complete even when a later
   pending `strix` commit status exists;
4. skips `workflow_dispatch` workflow runs in non-central `active_review_run_refs`
   so a same-head Deep job cannot return `already_running` and block
   `strix-scan`.

A successful `strix` commit status can still supersede a failed required check
run. That path informs a reviewer and remains the documented exception for
base-branch catch-up. It does not let a Deep check run park merge.

Do not fold this change into ContextualWisdomLab/.github#1054. That pull
request owns the official `quick|standard|deep` mapping. This record owns
merge-evidence isolation so #1054 can land without a six-hour merge stall.

## Verification contract

`tests/test_pr_review_merge_scheduler.py` fails if:

1. `PULL_REQUEST_FIELDS_FRAGMENT` drops `workflowRun.event`;
2. a running or failed `workflow_dispatch` Strix check run changes
   `strix_evidence_state` or `failed_status_checks` when a required check run
   is present;
3. a same-head `workflow_dispatch` workflow run is classified as current
   evidence in non-central `active_review_run_refs`;
4. `matching_actions_job_id` returns a Deep job over a required job.

## Rollback

Roll back only if a required `pull_request_target` or `strix-scan` check run is
observed ignored because GitHub omitted `event` and the run was mis-labeled
`workflow_dispatch`. Missing `event` stays required evidence.

## References (APA 7th)

GitHub. (n.d.-a). *Manually running a workflow*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

GitHub. (n.d.-b). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (n.d.-c). *Objects: WorkflowRun* (`event`). GitHub GraphQL API.
Retrieved August 16, 2026, from
https://docs.github.com/en/graphql/reference/objects#workflowrun
