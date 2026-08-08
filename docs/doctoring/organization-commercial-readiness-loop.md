# Organization commercial-readiness coordinator

## Decision

ContextualWisdomLab uses one organization-central hourly coordinator for repositories that do not already have an enabled dedicated commercial, maintenance, review-repair, or product-development writer. The coordinator complements rather than duplicates the existing 15-minute organization merge scheduler.

The coordinator may dispatch at most one review-repair workflow and one product-development workflow per hour. These may target different repositories, so review or check latency in one repository does not stop useful work in another. The coordinator never approves, merges, releases, edits source, or interprets a failed check as success by itself.

## Why this is realistic

A single workflow cannot safely write every repository merely because it runs in the organization `.github` repository. GitHub's default `GITHUB_TOKEN` is scoped to the repository containing the workflow; cross-repository Actions dispatch therefore requires an explicitly provisioned user or GitHub App credential with the required repository and Actions permissions. This control does not make every repository directly writable. It only considers repositories the live API reports as organization-owned, non-fork, enabled, non-archived, default-branch-bearing, and writable by the authenticated installation.

The central job therefore refuses both repository-scoped and reviewer-scoped token fallbacks. It requires the maintainer-scoped `PR_REVIEW_MERGE_TOKEN`; `OPENCODE_APPROVE_TOKEN` remains isolated to the reviewer credential chain and `GITHUB_TOKEN` is not accepted for cross-repository coordination. The coordinator itself receives neither `NVIDIA_NIM_API_KEY` nor `COPILOT_GITHUB_TOKEN`. Model credentials remain inside separately reviewed repository-local or central workers.

## Dynamic repository-writer lease

An active workflow with a scheduled high-signal commercial/development/maintenance/review-repair identity owns the repository writer lease. A queued or in-progress run with the same identity also owns a live lease. The organization coordinator skips that repository for the entire pass.

A disabled workflow does not hold a lease. A manual-only workflow does not hold a lease unless it is already running. If an active high-signal workflow exists but its source cannot be read, the coordinator fails closed and treats the repository as leased. The organization-required merge scheduler is explicitly excluded from this classification because it is a governance gate rather than a product-code writer.

Before every dispatch, the coordinator refetches the exact default-branch SHA, active workflow identities and source blobs, active runs, and open pull-request heads, bases, draft states, and update timestamps. Any change invalidates the predecessor snapshot. A newly appearing writer causes `skipped_writer_lease`; any other movement causes `skipped_state_changed`.

## Review-repair boundary

A repository with at least one non-draft pull request targeting its default branch may receive one `pr-review-fix-scheduler` repository dispatch. Draft and stacked pull requests are not treated as generic repair targets because the coordinator cannot safely infer their dependency order. The established central scheduler and autofix worker remain responsible for thread classification, current-head checks, path bounds, credential isolation, and whether a repair is actually warranted.

The existing organization merge scheduler continues to own review dispatch, branch updates, exact-head approval evaluation, direct or automatic merge, and branch-protection compliance. The hourly coordinator does not create a second merge implementation.

## Product-development boundary

Product development is dispatched only when a repository has zero open pull requests and exposes one active, manual-only, explicitly marked workflow:

```yaml
# cwl-org-commercial-entrypoint: v1
on:
  workflow_dispatch:
```

The entrypoint must contain an explicit `concurrency` contract, use `NVIDIA_NIM_API_KEY`, omit `COPILOT_GITHUB_TOKEN`, have no schedule of its own, and carry a commercial/product-development identity. This opt-in prevents the central coordinator from guessing that an unrelated manual workflow can safely modify product source. Repositories with an existing schedule keep their own lease and are never double-dispatched.

The repository-local entrypoint remains responsible for its own bounded editable paths, tests, 100% production statement and branch coverage, public docstrings, package and security verification, exact-head publication, and pull-request creation. A missing compliant entrypoint is a deliberate no-op, not permission to inject a generic writer into that repository.

## Failure and operations

The schedule runs at minute 7 rather than minute 0 to reduce exposure to the documented start-of-hour GitHub Actions load spike. The central workflow has no `workflow_dispatch` entrypoint, so branch-selected coordinator source cannot be executed; scheduled execution occurs only from protected default `main`. Local operators may use the script's `--dry-run` mode from a reviewed checkout without adding a central manual workflow entrypoint.

Organization and repository inventories are paginated. One inaccessible repository is recorded as an inspection error while other independently safe repositories continue.

No queued, pending, skipped-required, cancelled, absent, stale-head, predecessor-head, synthetic-merge-only, or failed check is converted to passing evidence. The coordinator's successful dispatch means only that exact state was revalidated and a bounded downstream workflow was accepted by GitHub.

Rollback is removal or disabling of `.github/workflows/organization-commercial-readiness-loop.yml`. Repository-local dedicated loops and the existing 15-minute merge scheduler remain independently operational.

## APA 7 references

GitHub. (n.d.). *Automatic token authentication*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows

GitHub. (n.d.). *REST API endpoints for workflows*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/workflows

GitHub. (n.d.). *REST API endpoints for workflow runs*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/workflow-runs

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218
