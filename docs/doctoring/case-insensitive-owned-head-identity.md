# Case-insensitive owned-head identity

Decision date: **2026-09-07**

## Problem

GitHub treats repository names case-insensitively, but the scheduler compared
`headRepository.nameWithOwner` with the configured target using exact string
equality. Casing drift could classify an organization-owned branch as an
external fork and build the wrong compare ref.

## Decision

Case-fold both repository identifiers in `same_repository_head` and
`compare_ref_for_pr_head`. No permission or ownership inference changes; only
names GitHub already considers identical are unified.

## Failure scenes

- `Owner/Repo` versus `owner/repo`: classify as the same repository.
- A genuinely different repository: retain external-head handling.
- Missing head repository metadata: preserve the existing compare fallback and
  fail-closed mutation eligibility.

## Evidence and follow-up

RED commit: `4fb514db54e6210fc0606f0dfa8d9033f3e1f6f5`.
Fresh exact-head hosted checks and independent review remain required.

## Reference

GitHub. (2026). *REST API endpoints for repositories*.
https://docs.github.com/en/rest/repos/repos
