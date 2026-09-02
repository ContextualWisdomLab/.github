# Hourly review-repair workflow registry retirement

## Status

Prepared 2026-09-02 for the single-file hourly review-repair consolidation in `ContextualWisdomLab/.github` PR #1673. This record addresses the control-plane lifecycle gap found during current-head review: deleting a workflow YAML path does not by itself prove what GitHub retained in the workflow registry.

## Problem and authority boundary

The consolidation intentionally replaces 18 scheduled caller files with `.github/workflows/hourly-review-repair.yml`. GitHub Actions keeps a repository workflow registry independently of the current Git tree, so source deletion and registry state must be reconciled explicitly rather than inferred. A removed path may still have a visible workflow identity requiring disablement, or it may already be absent from the complete paginated registry. This repository already treats orphan workflow identity state as a governance concern in `docs/doctoring/review-repair-quality-workflow-identity.md` and in the read-only orphan-inventory work tracked by `ContextualWisdomLab/.github#1026`.

The replacement scheduler must therefore be active before any visible legacy identity is retired. Source-file absence alone is not retirement evidence; the complete registry inventory is the evidence boundary. Conversely, registry retirement is control-plane lifecycle work only: it does not grant review, merge, repository-content, model-provider, or accounting authority.

## Migration contract

PR #1673 adds the one-shot compatibility workflow `.github/workflows/hourly-review-repair-registry-retirement.yml`. It has **no `workflow_dispatch` entrypoint**: its `actions: write` shell is executable only from reviewed source after a push to protected `main`. The job also checks `github.event_name == 'push'` and `github.ref == 'refs/heads/main'` before receiving destructive registry authority. On protected-`main` activation it:

1. enumerates the complete GitHub Actions workflow registry with pagination;
2. resolves exactly one registry identity for the consolidated replacement and requires its state to be `active` before any destructive mutation;
3. evaluates each of the 18 removed per-repository caller paths against that same immutable in-run inventory;
4. treats zero matches for a legacy path as already absent from the repository registry, accepts exactly one visible identity for mutation/verification, and fails closed on duplicate/ambiguous matches;
5. for a visible legacy identity, accepts only `active` or already-`disabled_manually`, disables `active` identities through the GitHub Actions disable endpoint, then reads the state back and requires `disabled_manually`;
6. rechecks that the replacement remains active after all legacy identities are reconciled; and
7. requires exactly one visible identity for the one-shot migration workflow and disables that identity last.

The migration has repository `actions: write` plus `contents: read`, no checkout, no model/reviewer secrets, no OIDC grant, no repository-content mutation, no schedule, and no arbitrary-branch manual dispatch. It fails closed on duplicate, unresolved, or unexpected visible registry states. A transient hosted-run failure is retried through GitHub's run/job retry controls against the same reviewed protected-main source rather than by dispatching a feature branch. The permanent consolidated scheduler retains its narrower read/OIDC dispatch permissions and does not inherit registry-mutation authority.

## 2026-09-02 Actions-capacity reconciliation

The first protected-main migration run remained queued on `ubuntu-24.04` while the central Actions control plane was already carrying a large standard-runner backlog. Because the purpose of this one-shot is itself to retire obsolete workflow identities that can contribute unnecessary Actions scheduling pressure, leaving the mutation on the saturated runner lane created an avoidable operability dependency. PR #1684 moved the retirement job to `ubuntu-slim`, which is sufficient for the shell-only `gh`/`jq` registry transaction and does not require checkout, language toolchains, containers, or privileged build tooling. This changed only runner admission; the protected-main event boundary, `actions: write` scope, replacement-active proof, registry enumeration, read-after-write verification, fail-closed handling, and self-disable-last ordering remained unchanged.

Protected-main run `33596622523`, job `100141255712`, then proved that the capacity repair worked: the job was admitted and began the registry transaction instead of remaining queued. It failed before the first mutation because the complete paginated registry contained **zero** entries for `.github/workflows/accounting-information-platform-hourly-review-repair.yml`. The original migration incorrectly treated both zero and duplicate matches as the same fatal ambiguity. Zero is not ambiguous for a removed legacy path: there is no visible registry identity to disable, whereas two or more matches remain unsafe and fail closed. The successor repair therefore distinguishes those cases while keeping the replacement and self identities exact-one requirements.

`tests/test_hourly_review_repair_registry_retirement.py` pins the capacity runner and the zero/one/many identity semantics so this one-shot cannot silently regress onto the saturated standard lane or treat an absent legacy identity as a failed mutation. Once hosted evidence proves every legacy path is either absent from the complete registry or `disabled_manually`, the replacement remains active, and the migration identity itself is `disabled_manually`, the source workflow and its migration-only test assertions should be removed together in the normal post-migration cleanup.

## Cleanup and evidence

The migration source must remain in protected `main` until a hosted run proves all 18 legacy paths are terminally reconciled—each either absent from the complete paginated workflow registry or represented by exactly one identity in `disabled_manually` state—while `.github/workflows/hourly-review-repair.yml` remains active and the migration identity itself reaches `disabled_manually`. After that evidence exists, remove the migration YAML in a normal protected-branch PR. Deleting it only after self-disable leaves its historical registry identity disabled rather than creating another enabled orphan. Do not claim the migration complete from PR checks alone; PR checks validate source contracts, while the registry transaction can occur only after the replacement is active on protected `main`.

## Regression contract

`tests/test_hourly_review_repair_registry_retirement.py` requires the one-shot workflow to have neither a schedule nor `workflow_dispatch`, to bind execution to protected-main push context, to name all 18 legacy paths exactly once, to prove the replacement active before the first disable request, to accept a zero-match legacy path as already absent while rejecting duplicates, to re-read and verify every visible disabled state, to disable itself last, to stay on the capacity-available `ubuntu-slim` lane while migration remains pending, and to avoid reviewer/model/provider credentials. The focused `Contextual Orchestrator Review Repair Quality CI` watches the migration workflow, this doctoring record, and the retirement contract test so a future change cannot bypass that regression. This complements `tests/test_hourly_review_repair_callers.py`, which continues to verify the 18-repository schedule/target/concurrency mapping in the single active scheduler file.

## References

GitHub, Inc. (n.d.). *REST API endpoints for workflows*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/rest/actions/workflows

ContextualWisdomLab. (2026). *Review-repair quality workflow identity RCA*. `docs/doctoring/review-repair-quality-workflow-identity.md`.

ContextualWisdomLab. (2026). *Inventory orphaned workflow identities* (`ContextualWisdomLab/.github#1026`). GitHub governance work.
