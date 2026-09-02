# Hourly review-repair workflow registry retirement

## Status

Completed on 2026-09-02. Protected-main run `33597034283`, job `100142454414`, on `ContextualWisdomLab/.github@6958918beaad96d0a67ce264706c828bb7f3f000` completed successfully. Its complete paginated workflow-registry inventory reported all 18 removed per-repository hourly review-repair paths already absent, revalidated the consolidated `.github/workflows/hourly-review-repair.yml` replacement as active, and then disabled the one-shot migration identity `.github/workflows/hourly-review-repair-registry-retirement.yml` as workflow id `348089470`. The post-success cleanup removes the disabled one-shot workflow source and its migration-only contract test, and removes their dead watch/compile entries from the permanent review-repair quality CI.

This record was prepared for the single-file hourly review-repair consolidation in `ContextualWisdomLab/.github` PR #1673. It preserves the control-plane lifecycle evidence that deleting a workflow YAML path does not by itself prove what GitHub retained in the workflow registry.

## Problem and authority boundary

The consolidation intentionally replaced 18 scheduled caller files with `.github/workflows/hourly-review-repair.yml`. GitHub Actions keeps a repository workflow registry independently of the current Git tree, so source deletion and registry state had to be reconciled explicitly rather than inferred. A removed path could still have a visible workflow identity requiring disablement, or it could already be absent from the complete paginated registry. This repository already treats orphan workflow identity state as a governance concern in `docs/doctoring/review-repair-quality-workflow-identity.md` and in the read-only orphan-inventory work tracked by `ContextualWisdomLab/.github#1026`.

The replacement scheduler therefore had to be active before any visible legacy identity was retired. Source-file absence alone was not retirement evidence; the complete registry inventory was the evidence boundary. Conversely, registry retirement was control-plane lifecycle work only: it did not grant review, merge, repository-content, model-provider, or accounting authority.

## Migration contract

PR #1673 added the one-shot compatibility workflow `.github/workflows/hourly-review-repair-registry-retirement.yml`. It had **no `workflow_dispatch` entrypoint**: its `actions: write` shell was executable only from reviewed source after a push to protected `main`. The job also checked `github.event_name == 'push'` and `github.ref == 'refs/heads/main'` before receiving destructive registry authority. On protected-`main` activation it:

1. enumerated the complete GitHub Actions workflow registry with pagination;
2. resolved exactly one registry identity for the consolidated replacement and required its state to be `active` before any destructive mutation;
3. evaluated each of the 18 removed per-repository caller paths against that same immutable in-run inventory;
4. treated zero matches for a legacy path as already absent from the repository registry, accepted exactly one visible identity for mutation/verification, and failed closed on duplicate/ambiguous matches;
5. for a visible legacy identity, accepted only `active` or already-`disabled_manually`, disabled `active` identities through the GitHub Actions disable endpoint, then read the state back and required `disabled_manually`;
6. rechecked that the replacement remained active after all legacy identities were reconciled; and
7. required exactly one visible identity for the one-shot migration workflow and disabled that identity last.

The migration had repository `actions: write` plus `contents: read`, no checkout, no model/reviewer secrets, no OIDC grant, no repository-content mutation, no schedule, and no arbitrary-branch manual dispatch. It failed closed on duplicate, unresolved, or unexpected visible registry states. The permanent consolidated scheduler retains its narrower read/OIDC dispatch permissions and does not inherit registry-mutation authority.

## 2026-09-02 Actions-capacity reconciliation

The first protected-main migration run remained queued on `ubuntu-24.04` while the central Actions control plane was already carrying a large standard-runner backlog. Because the purpose of this one-shot was itself to retire obsolete workflow identities that could contribute unnecessary Actions scheduling pressure, leaving the mutation on the saturated runner lane created an avoidable operability dependency. PR #1684 moved the retirement job to `ubuntu-slim`, which was sufficient for the shell-only `gh`/`jq` registry transaction and did not require checkout, language toolchains, containers, or privileged build tooling. This changed only runner admission; the protected-main event boundary, `actions: write` scope, replacement-active proof, registry enumeration, read-after-write verification, fail-closed handling, and self-disable-last ordering remained unchanged.

Protected-main run `33596622523`, job `100141255712`, proved that the capacity repair worked: the job was admitted and began the registry transaction instead of remaining queued. It failed before the first mutation because the complete paginated registry contained **zero** entries for `.github/workflows/accounting-information-platform-hourly-review-repair.yml`. The original migration incorrectly treated both zero and duplicate matches as the same fatal ambiguity. Zero is not ambiguous for a removed legacy path: there is no visible registry identity to disable, whereas two or more matches remain unsafe and fail closed. PR #1690 therefore distinguished those cases while keeping the replacement and self identities exact-one requirements.

Protected-main run `33597034283`, job `100142454414`, then closed the lifecycle loop: every one of the 18 legacy paths was reported `already absent from registry`, the replacement remained active through the final guard, and the migration identity was read back as retired after its disable call. The job completed successfully rather than relying on PR-check inference.

## Cleanup and evidence

The migration source was deliberately retained in protected `main` until hosted evidence proved all 18 legacy paths terminally reconciled, the replacement active, and the migration identity disabled. That proof now exists in run `33597034283` / job `100142454414`. The cleanup deletes `.github/workflows/hourly-review-repair-registry-retirement.yml` only after self-disable, deletes `tests/test_hourly_review_repair_registry_retirement.py` because it existed solely to protect the now-completed one-shot, and removes both obsolete paths from the permanent quality workflow's path/compile lists. The historical doctoring record remains because it is the durable provenance for why the registry mutation existed and why its source can now be safely absent.

## Durable regression boundary

The one-shot's zero/one/many identity semantics are no longer a live production contract after successful migration and source removal. The durable product/control-plane contract is now the consolidated `.github/workflows/hourly-review-repair.yml` scheduler plus `tests/test_hourly_review_repair_callers.py`, which continues to verify the 18-repository schedule/target/concurrency mapping. Future workflow-registry migrations must establish their own current inventory and fail-closed lifecycle evidence rather than depending on this retired migration implementation.

## References

GitHub, Inc. (n.d.). *REST API endpoints for workflows*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/rest/actions/workflows

ContextualWisdomLab. (2026). *Review-repair quality workflow identity RCA*. `docs/doctoring/review-repair-quality-workflow-identity.md`.

ContextualWisdomLab. (2026). *Inventory orphaned workflow identities* (`ContextualWisdomLab/.github#1026`). GitHub governance work.
