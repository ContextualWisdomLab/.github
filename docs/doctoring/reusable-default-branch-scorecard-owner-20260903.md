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
caller job. The called owner already coalesces duplicate invocations for the caller repository, ref, and exact
source SHA. A caller-side group with the same identity could cancel its own called workflow.

## Concurrency decision

GitHub concurrency admission follows event arrival order, not commit ancestry. A group containing only caller
repository and ref would therefore permit a delayed event for an older commit to cancel a scan already running
for a newer commit. The owner instead includes `${{ github.repository }}`, `${{ github.ref }}`, and
`${{ github.sha }}` in the group and uses `cancel-in-progress: true`. Only duplicate invocations for the same
immutable source revision can cancel one another; distinct revisions never share a cancellation boundary.

This choice deliberately does **not** use event arrival as a default-branch history oracle. Cross-revision queue
cleanup, when needed, belongs to a separate trusted worker that re-fetches the live default-branch SHA and
revalidates both candidate run identity and commit ancestry immediately before cancellation. Until that guarded
owner exists, retaining an older scan is safer than allowing it to destroy newer authoritative evidence.

This also differs deliberately from `Current Head Run Coalescer`: that workflow performs queue-cleanup mutation,
so its active worker must finish and only the latest pending trigger is retained.

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
