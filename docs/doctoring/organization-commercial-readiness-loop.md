# Organization commercial-readiness coordinator

## Decision

ContextualWisdomLab uses one organization-central hourly coordinator for repositories that do not already have an enabled dedicated commercial, maintenance, review-repair, or product-development writer. The coordinator complements rather than duplicates the existing 15-minute organization merge scheduler.

The coordinator may dispatch at most one review-repair workflow and one product-development workflow per hour. These may target different repositories, so review or check latency in one repository does not stop useful work in another. The coordinator never approves, merges, releases, edits source, or interprets a failed check as success by itself.

## Why this is realistic

A single workflow cannot safely write every repository merely because it runs in the organization `.github` repository. GitHub's default `GITHUB_TOKEN` is scoped to the repository containing the workflow; cross-repository Actions dispatch therefore requires an explicitly provisioned user or GitHub App credential with the required repository and Actions permissions. This control does not make every repository directly writable. It only considers repositories the live API reports as organization-owned, non-fork, enabled, non-archived, default-branch-bearing, and writable by the authenticated installation.

The central job therefore refuses both repository-scoped and reviewer-scoped token fallbacks. It prefers the maintainer-scoped `PR_REVIEW_MERGE_TOKEN`; when that optional long-lived secret is absent, the protected scheduled job exchanges its GitHub OIDC identity for the existing short-lived OpenCode GitHub App installation token. `OPENCODE_APPROVE_TOKEN` remains isolated to the reviewer credential chain and `GITHUB_TOKEN` is not accepted for cross-repository coordination. Both accepted credentials are exposed only to the final dispatch shell step, not checkout, setup, artifact upload, or other third-party actions. The OIDC exchange receives only `id-token: write`, which permits requesting the job-bound JWT but grants no repository write authority by itself. The exchanged installation token remains bounded by the App installation's selected repositories and permissions; GitHub still requires Contents write for `repository_dispatch` and Actions write for `workflow_dispatch`, so a missing installation permission fails closed. The coordinator itself receives neither `NVIDIA_NIM_API_KEY` nor `COPILOT_GITHUB_TOKEN`. Model credentials remain inside separately reviewed repository-local or central workers.

## Dynamic repository-writer lease

An active workflow with a scheduled high-signal commercial/development/maintenance/review-repair identity owns the repository writer lease. A queued, in-progress, waiting, pending, or requested run with the same identity also owns a live lease. The organization coordinator skips that repository for the entire pass.

A disabled workflow does not hold a lease. A manual-only workflow does not hold a lease unless it is already running. If an active high-signal workflow exists but its source cannot be read, the coordinator fails closed and treats the repository as leased. The organization-required merge scheduler is explicitly excluded from this classification because it is a governance gate rather than a product-code writer.

The coordinator lists workflow metadata for every repository but fetches exact workflow source only for identities that can plausibly be a repository writer. This keeps API use proportional to writer candidates rather than every ordinary CI, packaging, or security workflow. Active-run and pull-request inventories remain fully paginated, including writers beyond the first 100 queued or running executions.

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

## Failure, evidence, and operations

Runs `32560132644`, `32562851784`, `32565331074`, `32567859925`, and `32570355777` reproduced the same startup failure: the workflow required `PR_REVIEW_MERGE_TOKEN`, but neither the repository nor organization exposed that secret. The coordinator therefore completed no inventory or dispatch work for five consecutive hourly heartbeats. The OIDC installation-token fallback repairs that configuration deadlock without copying a personal token, accepting the repository-scoped `GITHUB_TOKEN`, or reusing `OPENCODE_APPROVE_TOKEN`.

The schedule runs at minute 7 rather than minute 0 to reduce exposure to the documented start-of-hour GitHub Actions load spike. The central workflow has no `workflow_dispatch` entrypoint, so branch-selected coordinator source cannot be executed; scheduled execution occurs only from protected default `main`. Local operators may use the script's `--dry-run` mode from a reviewed checkout without adding a central manual workflow entrypoint.

Organization, workflow, active-run, and pull-request inventories are paginated. One inaccessible repository is recorded as an inspection error while other independently safe repositories continue. A run fails nonzero when every selected repository inspection fails or when every planned dispatch fails; partial, independently contained failures remain visible without discarding successful work.

Exact-head reviews found three exchange-path gaps before activation. A
malformed HTTP-success OIDC or App-token response made `jq` exit under shell
`errexit` before the workflow could publish its explicit unavailable result;
the OIDC JWT was not registered with the runner masker; and the App exchange
ran even when the preferred maintainer secret was already present. The final
coordinator shell step now performs the exchange only when its preferred
`GH_TOKEN` input is empty, guards both JSON parses with a bounded fail-closed
diagnostic, and masks the OIDC JWT immediately after validation. Keeping
selection and exchange in that final first-party shell step preserves the rule
that no checkout, setup, artifact, or other third-party action receives either
credential, and neither response body is logged.

Each run writes one deterministic JSON receipt and the same bounded evidence to the GitHub Actions job summary. The JSON is uploaded through the immutable, SHA-pinned artifact action with a three-day retention period. Artifact upload receives no maintainer or model credential. The receipt proves only coordinator observations and downstream dispatch acceptance; it is not merge, release, or product-quality evidence.

No queued, pending, skipped-required, cancelled, absent, stale-head, predecessor-head, synthetic-merge-only, or failed check is converted to passing evidence. The coordinator's successful dispatch means only that exact state was revalidated and a bounded downstream workflow was accepted by GitHub.

Rollback is removal or disabling of `.github/workflows/organization-commercial-readiness-loop.yml`. Repository-local dedicated loops and the existing 15-minute merge scheduler remain independently operational.

## APA 7 references

GitHub. (n.d.). *Automatic token authentication*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows

GitHub. (n.d.). *OpenID Connect reference*. GitHub Docs. Retrieved August 22, 2026, from https://docs.github.com/en/actions/reference/security/oidc

GitHub. (n.d.). *REST API endpoints for artifacts*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/artifacts

GitHub. (n.d.). *REST API endpoints for workflows*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/workflows

GitHub. (n.d.). *REST API endpoints for repositories*. GitHub Docs. Retrieved August 22, 2026, from https://docs.github.com/en/rest/repos/repos

GitHub. (n.d.). *REST API endpoints for workflow runs*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/workflow-runs

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218
