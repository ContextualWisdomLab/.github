# Reusable default-branch Scorecard owner — 2026-09-03

## Incident and buyer-visible risk

Repository-local `scorecard-analysis.yml` files in `ContextualWisdomLab/wardnet` and
`ContextualWisdomLab/semantic-data-portal` repeat the same OSSF Scorecard, SARIF filtering, and upload
implementation. Open deletion PRs `wardnet#160` and `semantic-data-portal#93` assumed the organization-required
`scorecard-pr.yml` fully replaced them. That assumption is false: the required workflow supplies pull-request
evidence, while the local workflows supply default-branch push and weekly scheduled evidence. Deleting them
without a successor would stop branch-history and scheduled SARIF refresh.

The customer consequence is stale supply-chain posture after a merge: a pull request could be scanned before
landing, while the authoritative default branch and its later dependency/configuration drift receive no
corresponding Scorecard result.

## Owner decision

`ContextualWisdomLab/.github/.github/workflows/scorecard-analysis.yml` is the canonical implementation owner for
default-branch Scorecard analysis. It preserves its own `push` and `schedule` triggers and adds `workflow_call`
for product repositories. Consumers retain only the trigger and permission boundary that GitHub cannot express
centrally across independent repositories.

The called workflow uses the caller's `github` context and `actions/checkout` therefore checks out the caller
repository. The caller's `GITHUB_TOKEN` permissions cannot be elevated by the called workflow, so each caller
must explicitly grant the required permissions. Consumers must pin the reusable workflow to the full immutable
**central merge commit SHA**, never `main`, another mutable branch, or an open PR head.

## Canonical thin caller after this owner PR lands

Replace `<default_branch>` and `<central_merge_sha>` only after the central PR is merged:

```yaml
name: Scorecard analysis

on:
  push:
    branches: ["<default_branch>"]
  schedule:
    - cron: "30 1 * * 6"

permissions: read-all

jobs:
  scorecard_analysis:
    permissions:
      security-events: write
      id-token: write
      contents: read
      issues: read
      pull-requests: read
      checks: read
    uses: ContextualWisdomLab/.github/.github/workflows/scorecard-analysis.yml@<central_merge_sha>
```

Do not add `runs-on`, `steps`, copied Scorecard logic, inherited secrets, or a second concurrency group to the
caller job. The called owner already coalesces same-ref invocations; a caller-side group with an overlapping
identity could cancel its own called workflow.

## Concurrency decision

This PR's own earlier draft reasoned that GitHub concurrency admission follows event arrival order, not commit
ancestry, and scoped the group by `${{ github.repository }}`, `${{ github.ref }}`, and `${{ github.sha }}` with
`cancel-in-progress: true` so only duplicate invocations of the same immutable revision could cancel one another.
That reasoning is sound in isolation, but `.github#1768` (merged to `main` before this PR's own branch caught
up) had independently added a *different*, already-reviewed concurrency group to this same file: scoped by
`${{ github.ref }}` only, `cancel-in-progress: false`, so an in-flight scan for an older commit always finishes
and uploads that commit's SARIF evidence rather than being cancelled, and a burst of pushes queues (GitHub's
default single-pending-successor behavior) instead of running unboundedly in parallel.

**Merging this branch as-is produced two `concurrency:` keys in one YAML mapping -- a real bug, not a stylistic
duplication: YAML resolves a repeated mapping key to its last occurrence, so the SHA-scoped block was silently
discarded at parse time regardless of author intent.** The two designs are also structurally incompatible as a
single `concurrency:` block, not just redundant: SHA-scoping gives every distinct commit its own group, which
means NOTHING ever queues behind anything else -- restoring the unbounded-concurrent-scans problem `#1768`
exists to prevent. Given this organization's standing priority of reducing GitHub Actions queue congestion
(a plan-level 60-job ceiling shared across the whole org), `#1768`'s ref-scoped, cancel-false group was kept as
authoritative and this PR's SHA-scoped block was removed. The narrower concern the SHA-scoped design addressed
(a delayed duplicate event for the exact same commit) remains a real, if much rarer, residual risk -- not
closed here.

This also differs deliberately from the merge scheduler's integrated current-head coalescing step: that step performs queue-cleanup mutation, so its active worker must finish and only the latest pending trigger is retained.

## TDD and rollout evidence

- RED `76617d0a1f4bd0126d0e610362328ace2dd02612`: contract requires `workflow_call`, preserved push/schedule,
  reusable ownership, immutable action pins, credential hygiene, and SARIF upload behavior while the owner
  workflow still lacks the reusable contract.
- GREEN `aaf0fa5241348648e43618f949f44b82028abaa2`: owner workflow implements the initial reusable contract.
- Review RED `ef88c78aa64b6922f50d4a6a3e34f1900d04694f`: parsed-YAML contracts require the exact-SHA concurrency
  boundary while production still groups only by repository/ref. The same commit replaces comment-sensitive
  substring checks with structural YAML assertions.
- Review GREEN `7f99d560e8eaa9ab2cec46600b3321e9b0700669`: production adds the exact source SHA to the group and records
  the owner boundary for any future cross-revision cleanup.
- Focused reconstructed exact-content test before review: `3 passed`.
- **Post-review correction, before merge:** `.github#1768` landed its own, incompatible concurrency group for
  this same file while this PR's branch was still in flight (see "Concurrency decision" above). The exact-SHA
  group GREEN commit above is accurate as a record of this PR's own development, but is NOT the state that
  merged -- the final concurrency block keeps `#1768`'s ref-scoped, `cancel-in-progress: false` group instead.
- Rollout remains incomplete until the central PR merges and each consumer pins the resulting merge SHA.

## Consumer acceptance criteria

For each consumer repository:

1. Re-fetch the default branch and deletion-PR exact head.
2. Replace local implementation with the thin caller pinned to the central merge SHA.
3. Preserve the repository's actual default branch and weekly schedule.
4. Update repository documentation that names the local implementation.
5. Prove a default-branch push or governed canary invokes the central workflow in the caller context, checks out
   the consumer commit, produces Scorecard output, and attempts SARIF upload under the declared permissions.
6. Confirm the central PR-required Scorecard and default-branch caller do not both trigger for the same event.
7. Confirm a delayed older-revision event cannot cancel a newer-revision scan.
8. Merge through ordinary protection unless the exact central queue-control chicken-and-egg condition applies.

`wardnet#160` and `semantic-data-portal#93` remain open repair branches until these criteria are satisfied; they
must not be closed merely to reduce the PR count.

## References

GitHub. (2026). *Reusing workflow configurations*. GitHub Docs.
https://docs.github.com/actions/reference/workflows-and-actions/reusing-workflow-configurations

GitHub. (2026). *Reuse workflows*. GitHub Docs.
https://docs.github.com/actions/how-tos/reuse-automations/reuse-workflows

GitHub. (2026). *Control the concurrency of workflows and jobs*. GitHub Docs.
https://docs.github.com/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

Open Source Security Foundation. (2026). *OSSF Scorecard action*. GitHub.
https://github.com/ossf/scorecard-action
