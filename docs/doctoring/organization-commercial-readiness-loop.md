# Organization commercial-readiness coordinator

## Decision

ContextualWisdomLab uses one organization-central hourly coordinator for repositories that do not already have an enabled dedicated commercial, maintenance, review-repair, or product-development writer. The coordinator complements rather than duplicates the existing 15-minute organization merge scheduler.

The coordinator may dispatch at most one review-repair workflow and one product-development workflow per hour. These may target different repositories, so review or check latency in one repository does not stop useful work in another. The coordinator never approves, merges, releases, edits source, or interprets a failed check as success by itself.

## Why this is realistic

A single workflow cannot safely write every repository merely because it runs in the organization `.github` repository. GitHub's default `GITHUB_TOKEN` is scoped to the repository containing the workflow; cross-repository Actions dispatch therefore requires an explicitly provisioned user or GitHub App credential with the required repository and Actions permissions. This control does not make every repository directly writable. It only considers repositories the live API reports as organization-owned, non-fork, enabled, non-archived, default-branch-bearing, and writable by the authenticated installation.

The central job therefore refuses repository-scoped and reviewer-scoped token fallbacks. It prefers the maintainer-scoped `PR_REVIEW_MERGE_TOKEN`; when that credential is absent, the scheduled default-branch job may exchange its job-bound GitHub OIDC identity for the existing short-lived OpenCode App installation token. Both exchange calls have bounded connection and total timeouts, both returned tokens are masked before reuse, and malformed or empty responses fail closed. `OPENCODE_APPROVE_TOKEN` remains isolated to the reviewer credential chain and `GITHUB_TOKEN` is never accepted for cross-repository coordination. The resulting maintainer credential is exposed only to the final dispatch shell step, not checkout, setup, artifact upload, or other third-party actions. The coordinator itself receives neither `NVIDIA_NIM_API_KEY` nor `COPILOT_GITHUB_TOKEN`. Model credentials remain inside separately reviewed repository-local or central workers.

## Dynamic repository-writer lease

An active workflow with a scheduled high-signal commercial/development/maintenance/review-repair identity owns the repository writer lease. A queued, in-progress, waiting, pending, or requested run with the same identity also owns a live lease. The organization coordinator skips that repository for the entire pass.

A disabled workflow does not hold a lease. A manual-only workflow does not hold a lease unless it is already running. If an active high-signal workflow exists but its source cannot be read, the coordinator fails closed and treats the repository as leased. The organization-required merge scheduler is explicitly excluded from this classification because it is a governance gate rather than a product-code writer.

The coordinator lists workflow metadata for every repository but fetches exact workflow source only for identities that can plausibly be a repository writer. This keeps API use proportional to writer candidates rather than every ordinary CI, packaging, or security workflow. Active-run and pull-request inventories remain fully paginated, including writers beyond the first 100 queued or running executions.

Before every dispatch, the coordinator refetches the exact default-branch SHA, active workflow identities and source blobs, active runs, and open pull-request heads, bases, draft states, and update timestamps. Any change invalidates the predecessor snapshot. A newly appearing writer causes `skipped_writer_lease`; any other movement causes `skipped_state_changed`.

## Review-repair boundary

A repository with at least one non-draft pull request targeting its default branch may receive one `pr-review-fix-scheduler` repository dispatch. Draft and stacked pull requests are not treated as generic repair targets because the coordinator cannot safely infer their dependency order. The established central scheduler and autofix worker remain responsible for thread classification, current-head checks, path bounds, credential isolation, and whether a repair is actually warranted.

The existing organization merge scheduler continues to own review dispatch, branch updates, exact-head approval evaluation, direct or automatic merge, and branch-protection compliance. The hourly coordinator does not create a second merge implementation.

## Product-development boundary

Product development is dispatched only when a repository has zero open pull requests and exposes one active, manual-only, explicitly marked workflow. The repository owns the human-readable prompt, which may use any language. Eligibility depends on a versioned machine-readable capability set and an executable binding rather than copied English prose.

```yaml
# cwl-org-commercial-entrypoint: v1
# cwl-ddd-architecture-audit: required
on:
  workflow_dispatch:

concurrency:
  group: product-development

env:
  NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
  CWL_DDD_CONTRACT_VERSION: "1"
  CWL_DDD_CONTRACT_CAPABILITIES: >-
    aggregate anti_corruption_layer bounded_context context_map
    directory_ownership domain_event domain_service entity invariant
    minimal_shared_kernel product_gap_baseline repository
    subdomain_classification ubiquitous_language value_object
  CWL_PRODUCT_AGENT_PROMPT: |
    Deliver one buyer-visible increment through the repository-owned product agent.

jobs:
  develop:
    steps:
      - name: Invoke the repository product agent
        run: |
          # cwl-ddd-prompt-binding: v1
          product-agent \
            --prompt-env CWL_PRODUCT_AGENT_PROMPT \
            --architecture-contract-env CWL_DDD_CONTRACT_CAPABILITIES
```

The root workflow `env` mapping must contain exactly one non-empty `CWL_PRODUCT_AGENT_PROMPT`, one exact version-one capability block, and one version value. The capability set is closed for version one; missing, misspelled, duplicated, or unversioned values fail closed. The prompt and capability environment names must reach the same non-comment shell command under the binding marker. Comments, unrelated YAML, nested or duplicate environment scopes, inert block scalars, shell built-ins, malformed quoting, dangling continuations, and flags split across commands do not satisfy the contract.

The capability IDs cover the strategic and tactical Domain-Driven Design obligations required by the organization: core/supporting/generic subdomain classification, Bounded Context, Context Map, Ubiquitous Language, Aggregate, Entity, Value Object, Domain Service, Repository, Domain Event, Invariant, Anti-Corruption Layer, minimal Shared Kernel, directory ownership, and product-gap baseline traceability. Human-readable instructions can evolve independently as long as the repository product-agent adapter consumes both bound inputs and implements the declared version.

Each hourly product increment must identify the owning product responsibility before selecting a repository, then compare the live directory tree, module/package names, API, database objects, tests, and documentation with that responsibility. Misleading directory paths, generic `utils`/`common` dumping grounds that own domain behavior, infrastructure imports inside the domain model, cross-context database access, obsolete product names, or customer-visible implementation boundaries are architecture defects, not cosmetic debt. When one can be corrected safely in the bounded increment, the agent moves the code and updates imports, package manifests, call sites, migrations, tests, ADRs, diagrams, and compatibility adapters in the same pull request.

The contract does not impose one universal folder template. A move is justified by domain ownership and dependency direction, not by directory aesthetics. Aggregate boundaries remain the smallest consistency boundary; external and legacy systems are isolated behind an Anti-Corruption Layer; the Shared Kernel remains minimal; and cross-context integration uses explicit versioned contracts. If a coherent move exceeds the current pull request's safe scope, the agent must record the exact owner, callers, target context, migration sequence, and acceptance evidence in `docs/product-technical-gap-baseline.md` and select it as the next bounded architecture increment rather than silently leaving the drift unresolved.

This opt-in prevents the central coordinator from guessing that an unrelated manual workflow can safely modify product source. Repositories with an existing hourly or more frequent dedicated writer keep their own lease and are never double-dispatched; those schedules may share the same DDD contract and should adopt it without adding another cron.

The repository-local entrypoint remains responsible for bounded editable paths, tests, 100% production statement and branch coverage, public docstrings, package and security verification, exact-head publication, and pull-request creation. A missing compliant entrypoint is a deliberate no-op, not permission to inject a generic writer into that repository.

## Failure, evidence, and operations

The schedule runs at minute 7 rather than minute 0 to reduce exposure to the documented start-of-hour GitHub Actions load spike. The central workflow has no `workflow_dispatch` entrypoint, so branch-selected coordinator source cannot be executed; scheduled execution occurs only from protected default `main`. Local operators may use the script's `--dry-run` mode from a reviewed checkout without adding a central manual workflow entrypoint.

Organization, workflow, active-run, and pull-request inventories are paginated. One inaccessible repository is recorded as an inspection error while other independently safe repositories continue. A run fails nonzero when every selected repository inspection fails or when every planned dispatch fails; partial, independently contained failures remain visible without discarding successful work.

Each run writes one deterministic JSON receipt and the same bounded evidence to the GitHub Actions job summary. The JSON is uploaded through the immutable, SHA-pinned artifact action with a three-day retention period. Artifact upload receives no maintainer or model credential. The receipt proves only coordinator observations and downstream dispatch acceptance; it is not merge, release, or product-quality evidence.

No queued, pending, skipped-required, cancelled, absent, stale-head, predecessor-head, synthetic-merge-only, or failed check is converted to passing evidence. The coordinator's successful dispatch means only that exact state was revalidated and a bounded downstream workflow was accepted by GitHub.

Rollback is removal or disabling of `.github/workflows/organization-commercial-readiness-loop.yml`. Repository-local dedicated loops and the existing 15-minute merge scheduler remain independently operational.

## APA 7 references

Evans, E. (2004). *Domain-driven design: Tackling complexity in the heart of software*. Addison-Wesley.

Evans, E. (2015). *Domain-driven design reference: Definitions and pattern summaries*. Domain Language. https://www.domainlanguage.com/ddd/reference/

International Organization for Standardization, International Electrotechnical Commission, & Institute of Electrical and Electronics Engineers. (2022). *Software, systems and enterprise—Architecture description* (ISO/IEC/IEEE Standard 42010:2022). https://www.iso.org/standard/74393.html

GitHub. (n.d.). *Automatic token authentication*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows

GitHub. (n.d.). *REST API endpoints for artifacts*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/artifacts

GitHub. (n.d.). *REST API endpoints for workflows*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/workflows

GitHub. (n.d.). *REST API endpoints for workflow runs*. GitHub Docs. Retrieved August 8, 2026, from https://docs.github.com/en/rest/actions/workflow-runs

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218
