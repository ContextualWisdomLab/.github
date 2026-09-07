# Manual Strix workflow dispatch is not scheduler evidence

검토 기준일: **2026-09-07**

## Problem

A caller-selected `workflow_dispatch` run can use the same workflow and job
display names as the required Strix run. If the scheduler deduplicates only by
those names, a newer manual Deep run can hide, block, or become the rerun target
for required `pull_request_target` or `repository_dispatch` evidence.

## Decision

The central scheduler reads `checkSuite.workflowRun.event` in every paginated
GraphQL context page. CheckRun rerun identity is
`(workflow name, job name, event)`. A `workflow_dispatch` CheckRun is excluded
from Strix evidence, failed-check collection, action-required collection, job
selection, and active-run suppression.

A classic successful `strix` commit status remains a bounded reviewer signal
for the self-modifying base-branch catch-up case. It does not replace GitHub's
required CheckRun at merge time.

Missing event data is not classified as manual and therefore remains
authoritative/fail-closed. The repair does not weaken a required failure and
does not synthesize success.

## Verification contract

`tests/test_strix_manual_dispatch_isolation.py` proves that a newer manual run
cannot deduplicate away an older required failure, cannot become a rerun target,
cannot create ACTION_REQUIRED debt, and cannot suppress the required dispatch.
Hosted exact-head checks remain mandatory.

## Status and rollback

Status: **Proposed** in ContextualWisdomLab/.github#1061. Protected `main`
remains the release authority. Roll back only if GitHub stops exposing
`WorkflowRun.event`; absence must continue to fail closed as non-manual.

## References

GitHub. (n.d.). *Manually running a workflow*. GitHub Docs. Retrieved September
7, 2026, from https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

GitHub. (n.d.). *Objects: WorkflowRun*. GitHub GraphQL API. Retrieved September
7, 2026, from https://docs.github.com/en/graphql/reference/objects#workflowrun
