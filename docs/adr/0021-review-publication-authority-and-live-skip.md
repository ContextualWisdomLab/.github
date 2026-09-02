# ADR-0021: Publication authority freshness and live-skip propagation

- Status: accepted
- Date: 2026-09-02
- Scope: central Required Noema Review and Strix `repository_dispatch` control-plane paths

## Context

Long-running central review separates model execution from publication. The original Noema two-phase design refreshed a repository-scoped GitHub App token for the final write, but the publication-boundary live-PR lookup still ran first with the central `.github` `github.token`. That token cannot authoritatively inspect a private sibling repository. The OIDC path also retained its pre-model exchanged token across the model call, recreating the same lifetime risk already observed for GitHub App installation tokens.

Strix has a separate live-state issue: a `repository_dispatch` can be valid when queued but refer to a PR that is closed or draft when execution begins. The scan job correctly emits `should_scan=false` for those exact-head resolved/non-reviewable states. That decision must cross the job boundary; otherwise the separate privileged status-publication job can still start after the scan has deliberately skipped.

## Decision

1. Noema model preparation never grants predecessor evidence publication authority. After a publishable envelope exists, the selected reviewer source is refreshed before the publication-boundary live read: GitHub App mints a new repository-scoped installation token, OIDC obtains a new identity token and exchanges it for a new repository-scoped app token, and PAT remains the explicitly selected secret authority.
2. `Revalidate live Noema target before publication` and `Publish prepared Noema verdict on the exact live head` use the same selected publication-phase authority. They must not use the pre-model App/OIDC token, `github.token`, PR-author credentials, or an implicit fallback. Missing fresh authority fails closed.
3. Exact head/state/draft remain authoritative at publication time. A moved head is an error; a closed/draft exact head is resolved/non-reviewable work and produces no publication.
4. Strix exports the live admission decision from its scan job. The separate `publish-manual-pr-evidence-status` job may start only when `needs.strix.outputs.should_scan == 'true'`. False or absent authority does not publish a status.
5. Executable regressions must cover the publication-token ordering/selection and the Strix cross-job skip boundary. Completed source-fix workflows and their unique drivers are removed after the repair is materialized.

## Consequences

Private sibling Noema review no longer depends on the central repository token at the publication boundary, and both renewable reviewer identities are protected from long model-call expiry. Strix no longer spends a privileged status-publisher job on a dispatch the live scan admission gate has already rejected. These are authority/admission corrections only; required branch-protection contexts, substantive security findings, and exact-head evidence requirements are not weakened.
