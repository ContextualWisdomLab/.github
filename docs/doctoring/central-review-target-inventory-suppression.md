# Central review target-inventory suppression

Decision date: **2026-09-07**

## Problem

When the trusted reviewer is hosted centrally, target-repository old-head
workflow runs are not the authority for the central current-head verdict.
Enumerating those target runs before dispatch consumes the cross-repository
Actions credential and can exhaust its App quota before useful review work
starts.

## Decision

Compare the configured review dispatch repository with the target repository.
If they differ, do not enumerate or cancel target old-head runs from this
decision path. The central reviewer owns its own run lifecycle in the dispatch
repository. If they are the same repository, retain existing stale-run cleanup.

## Failure scenes

- Central review of a target repository: no target Actions inventory read occurs.
- Same-repository review: stale old-head runs are still cancelled.
- Repository name casing differs: case-insensitive identity prevents accidental
  cross-repository classification.

## Evidence and follow-up

RED commit: `08a16caa4fdb0d0d86c44bb8cd7aed611beaab7b`.
Fresh exact-head hosted checks and independent review remain required.

## Reference

GitHub. (2026). *REST API endpoints for workflow runs*.
https://docs.github.com/en/rest/actions/workflow-runs
