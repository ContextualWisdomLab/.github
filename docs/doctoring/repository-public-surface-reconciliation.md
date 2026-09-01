# Repository public-surface reconciliation — operational baseline

**Recorded:** 2026-09-01
**Owner:** `ContextualWisdomLab/.github`
**Applies to:** repository descriptions, topics, GitHub Pages settings, exact Ask DeepWiki preconditions, and reviewed issue/PR label assignments.

## Problem statement

The organization had repository-facing state that could be observed but not consistently mutated through the connected GitHub client. Concrete examples included an internal-instruction-heavy CalendarWeave description, empty repository topics on new bounded-context repositories, `has_pages=false` despite reviewed documentation sources being prepared, and label normalization that depended on one-off manual edits. A second central metadata PR also created a competing writer for the same control-plane responsibility.

Reporting those limitations was insufficient because the organization already owns a central GitHub Actions/API control plane. The repair therefore belongs in `.github`: reviewed desired state plus a least-privilege, protected-default-branch reconciliation path.

## Current control loop

```mermaid
flowchart TD
  Manifest["repository-metadata.json"]
  Taxonomy["repository-label-taxonomy.json"]
  Validate["read-only PR validation"]
  Leaf["leaf README + reviewed Pages source on default branch"]
  Apply["trusted .github/main apply"]
  Metadata["description + topics"]
  Pages["legacy /docs reconcile OR workflow mode preserve"]
  Labels["reviewed issue/PR label assignments"]
  Verify["re-read live public state"]

  Manifest --> Validate
  Taxonomy --> Validate
  Leaf --> Validate
  Validate --> Apply
  Apply --> Metadata
  Apply --> Pages
  Apply --> Labels
  Metadata --> Verify
  Pages --> Verify
  Labels --> Verify
```

The fleet loop is deliberately non-blocking. Every repository or label assignment is attempted independently, failures are collected, and the process reports the aggregate only after reachable siblings have been tried. A missing leaf README badge or Pages source therefore blocks only that repository's public-setting mutation.

## Safety and authority

- Pull-request validation has `contents: read` only. It cannot mutate repository settings or labels.
- Apply runs only when the scheduled workflow is executing from trusted `refs/heads/main` after validation.
- The apply step uses the established maintainer credential rather than widening the ordinary workflow token.
- Repository README changes remain leaf-owned. The central reconciler verifies exact DeepWiki linkage but never fabricates or silently edits customer-facing README copy.
- Pages has two reviewed deployment modes. Legacy mode requires a regular `docs/index.md` file on the live default branch. Explicit `pages_mode: workflow` requires a regular `.github/workflows/pages.yml` file **and** an already-configured live Pages site whose `build_type` is `workflow`.
- Workflow mode is preserve-only: the reconciler does not create or convert the Pages configuration. Missing Pages, a legacy live configuration, a directory at the required workflow path, or a missing workflow file fails before description/topic/Page writes for that repository.
- Legacy Pages remains convergent: absent sites are created, drifted legacy `/docs` sites are updated, disabled sites are deleted, and already-correct sites receive no write.
- Contents API source checks require a single object with `type: file`; directory objects and directory listings do not count as reviewed source evidence.
- Label reconciliation adds and removes only taxonomy-managed labels through individual label endpoints, so unrelated labels added by people or automation are not replaced from a stale snapshot.
- Pull-request metadata validation uses the stable `repository-metadata-reconcile-${{ github.ref }}` concurrency lineage and cancels superseded PR runs. The scheduled trusted apply remains non-cancellable, preventing a replacement heartbeat from abandoning a partially updated fleet.
- The repository's control-plane contract intentionally exposes no branch-selectable `workflow_dispatch` entrypoint; remediation follows the trusted default-branch schedule and normal rerun/governance paths.

## Desired-state fleet in this increment

The repository metadata manifest covers 22 reviewed repositories whose public-surface work has a concrete leaf source or active writer: `CalendarWeave`, `ConceptWeave`, `context-graph-contracts`, `ThreadWeave`, `RankWeave`, `fast-mlsirm`, `EgressWeave`, `psychometrics-commons`, `keyverse`, `OriginWeave`, `accounting-information-platform`, `pg-erd-cloud`, `clearfolio`, `DiagramWeave`, `semantic-data-portal`, `contextual-orchestrator`, `mhtml-etl-gateway`, `PolicyWeave`, `supply-chain-control-plane`, `learning-management-platform`, `learning-content-studio`, and `learning-record-store`.

EgressWeave and Psychometrics Commons joined the original fleet after their exact-cased DeepWiki badges and bounded `docs/index.md` Pages sources reached their protected default branches. Later entries are deliberately declared before live convergence only when an owned leaf lane exists for the required badge and Pages source. Until those prerequisites reach each protected default branch, that repository fails closed while sibling repositories remain independently actionable. The `semantic-data-portal` desired description also removes the internal `(PRD/TRD draft implementation)` qualifier rather than propagating it to the customer-facing repository surface.

The newest cohort has explicit source ownership: `ContextualWisdomLab/PolicyWeave#1` carries its exact-cased badge and `docs/index.md`; `ContextualWisdomLab/supply-chain-control-plane#1` carries its exact badge and bounded Pages landing source on the active product writer; `ContextualWisdomLab/learning-management-platform#1` owns the product-first README badge and `docs/index.md`; `ContextualWisdomLab/learning-content-studio#1` now owns its product-first README, exact badge, Apache-2.0 grant, and the `docs/index.md` content folded from closed child #8; and `ContextualWisdomLab/learning-record-store#1` now owns its product-first README, exact badge, Apache-2.0 grant, and the bounded `docs/index.md` content folded from closed child #7. The closed child PRs retain discussion history but no longer own unique public-surface source. Their live repositories still report Pages disabled until protected integration and trusted reconciliation complete.

An Actions-backed repository is not enrolled merely because `pages_mode: workflow` is supported. Enrollment requires an explicit reviewed manifest change after the repository's standard Pages workflow and live `build_type: workflow` configuration both exist. This preserves the deployment architecture of repositories such as ScopeWeave instead of silently rewriting them to legacy `/docs`.

The explicit label assignments on protected main remain a separate reviewed taxonomy lane. Richer repository-local labels such as priority, status, and `type: maintenance` are preserved when those labels are outside the centrally managed semantic set.

## Verification contract

A central source commit is not completion. After protected integration and apply, the operator or automation must re-read each affected repository and verify:

1. the live description equals reviewed desired state;
2. live topics equal the normalized desired set;
3. the default-branch README carries the exact linked DeepWiki badge when requested;
4. the selected Pages source is a regular file on the protected default branch: `docs/index.md` for legacy mode or `.github/workflows/pages.yml` for workflow mode;
5. legacy mode uses the intended default branch and `/docs`; workflow mode remains `build_type: workflow` and is never converted by the reconciler;
6. the Pages status is `built`, its URL remains under `https://contextualwisdomlab.github.io`, and the published endpoint returns non-empty content before publication is claimed;
7. reviewed issue/PR targets carry the desired managed label while unrelated labels remain intact.

GitHub's current REST Pages contract supports `build_type` values `legacy` and `workflow`, and branch sources with `/` or `/docs`. Current fleet entries use the legacy `/docs` contract unless an entry explicitly declares `pages_mode: workflow`. The workflow mode exists to preserve a repository whose deployment is already owned by a reviewed GitHub Actions workflow; it is not a central creation/conversion mechanism.

## Workflow-mode operating procedure

1. Land and review the repository-local `.github/workflows/pages.yml` on the protected default branch.
2. Verify the repository already has a live GitHub Pages configuration with `build_type: workflow`; do not rely on a PR branch or workflow filename alone.
3. Add `"pages": true` and `"pages_mode": "workflow"` to the exact-cased repository record in `config/repository-metadata.json`.
4. Let read-only PR validation prove manifest/source contracts and stale-run cancellation without settings write authority.
5. After protected integration, let the trusted scheduled reconciler preflight the workflow source and live deployment mode **before** any description/topic mutation.
6. Re-read description, topics, Pages build type, publication status, organization-owned URL, and non-empty live content. Only then mark the public-surface reconciliation complete.
7. If the workflow file disappears or the live deployment changes away from `workflow`, the repository fails closed and receives no metadata write until the repository-owned deployment boundary is repaired.

## Known integration boundary

Until this 22-repository desired-state extension reaches protected `.github/main`, its additional settings reconciliation cannot run from the trusted control plane. Leaf PRs whose badge or Pages source is still branch-only remain repository-local precondition blockers. These are integration states, not reasons to idle the fleet: continue eligible siblings, labels, and independent public-surface work while blocked leaves fail closed.
