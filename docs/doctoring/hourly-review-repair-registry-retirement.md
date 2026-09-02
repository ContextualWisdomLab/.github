# Hourly review-repair workflow registry retirement

## Status

Prepared 2026-09-02 for the single-file hourly review-repair consolidation in `ContextualWisdomLab/.github` PR #1673. This record addresses the control-plane lifecycle gap found during current-head review: deleting a workflow YAML path does not prove that GitHub has retired the corresponding workflow registry identity.

## Problem and authority boundary

The consolidation intentionally replaces 18 scheduled caller files with `.github/workflows/hourly-review-repair.yml`. GitHub Actions, however, keeps workflow registry identities independently of the current Git tree. A source deletion can therefore leave an enabled identity that no longer has an obvious owner path. This repository already treats that as a governance defect in `docs/doctoring/review-repair-quality-workflow-identity.md` and in the read-only orphan-inventory work tracked by `ContextualWisdomLab/.github#1026`.

The replacement scheduler must therefore be active before legacy identities are retired. Source-file absence is not retirement evidence. Conversely, registry retirement is control-plane lifecycle work only: it does not grant review, merge, repository-content, model-provider, or accounting authority.

## Migration contract

PR #1673 adds the one-shot compatibility workflow `.github/workflows/hourly-review-repair-registry-retirement.yml`. On protected `main` activation it:

1. enumerates the complete GitHub Actions workflow registry with pagination;
2. resolves exactly one registry identity for the consolidated replacement and requires its state to be `active` before any destructive mutation;
3. resolves exactly one registry identity for each of the 18 removed per-repository callers;
4. accepts only `active` or already-`disabled_manually` legacy states, disabling `active` identities through the GitHub Actions disable endpoint;
5. reads every mutated workflow identity back and requires `disabled_manually` rather than treating a successful HTTP mutation as sufficient evidence;
6. rechecks that the replacement remains active after all legacy identities are retired; and
7. disables the one-shot migration workflow's own registry identity last.

The migration has repository `actions: write` plus `contents: read`, no checkout, no model/reviewer secrets, no OIDC grant, no repository-content mutation, and no schedule. It fails closed on missing, duplicate, unresolved, or unexpected registry states. The permanent consolidated scheduler retains its narrower read/OIDC dispatch permissions and does not inherit registry-mutation authority.

## Cleanup and evidence

The migration source must remain in protected `main` until a hosted run proves all 18 legacy identities and the migration identity itself are `disabled_manually` while `.github/workflows/hourly-review-repair.yml` remains active. After that evidence exists, remove the migration YAML in a normal protected-branch PR. Deleting it only after self-disable leaves its historical registry identity disabled rather than creating another enabled orphan. Do not claim the migration complete from PR checks alone; PR checks validate source contracts, while the registry mutation can occur only after the replacement is active on protected `main`.

## Regression contract

`tests/test_hourly_review_repair_registry_retirement.py` requires the one-shot workflow to have no schedule, to name all 18 legacy paths exactly once, to prove the replacement active before the first disable request, to re-read and verify every disabled state, to disable itself last, and to avoid reviewer/model/provider credentials. This complements `tests/test_hourly_review_repair_callers.py`, which continues to verify the 18-repository schedule/target/concurrency mapping in the single active scheduler file.

## References

GitHub, Inc. (n.d.). *REST API endpoints for workflows*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/rest/actions/workflows

ContextualWisdomLab. (2026). *Review-repair quality workflow identity RCA*. `docs/doctoring/review-repair-quality-workflow-identity.md`.

ContextualWisdomLab. (2026). *Inventory orphaned workflow identities* (`ContextualWisdomLab/.github#1026`). GitHub governance work.
