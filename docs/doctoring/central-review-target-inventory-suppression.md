# Central review workflow-authority filtering

Decision date: **2026-09-07**

## Problem

When the trusted reviewer is hosted centrally, target-repository OpenCode
workflow runs are not the authority for the central current-head verdict.
The first implementation therefore skipped the target repository's entire
old-head Actions inventory. That also preserved stale target-owned CodeQL,
Python Security, and other direct pull-request runs, whose lifecycle remains
the target repository's responsibility.

## Decision

Always retain target-repository stale-run inventory and the existing
destructive-boundary live PR/head revalidation. When the configured review
dispatch repository differs from the target, exclude only bare or rendered
OpenCode workflow names from the target cancellation candidates; the central
reviewer owns those runs in the dispatch repository. Target-owned CodeQL,
security, and other direct workflows remain eligible for proven-old-head
cancellation. When repository identities match case-insensitively, retain
unfiltered cleanup.

## Failure scenes

- Central review of a target repository: stale OpenCode names are excluded, but
  stale target-owned CodeQL and security runs remain cancellable.
- Rendered GitHub run names such as
  `OpenCode Review Dispatch owner/repo#1@<sha>` receive the same boundary as
  their bare workflow names.
- Same-repository review: stale old-head cleanup remains unfiltered.
- Repository name casing differs: case-insensitive identity prevents accidental
  cross-repository classification.

## Evidence and follow-up

The original RED commit
`08a16caa4fdb0d0d86c44bb8cd7aed611beaab7b` covered only the unsafe broad
suppression. Corrective RED commits
`234d98dec14ae7a91819857f561b78d0d424ec98` and
`32a0d66cd1210f6fae1cb675265ce4ce49f63167` prove the workflow-authority
filter, unrelated target-workflow preservation, central invocation, and
case-insensitive same-repository boundary.
Fresh exact-head hosted checks and independent review remain required.

## Reference

GitHub. (2026). *REST API endpoints for workflow runs*.
https://docs.github.com/en/rest/actions/workflow-runs
