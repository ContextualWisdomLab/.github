# ADR-0021: Publication authority freshness and live-skip propagation

- Status: proposed
- Date: 2026-09-02
- Scope: central Required Noema Review and Strix `repository_dispatch` control-plane paths

## Context

Long-running central review separates model execution from publication. The original Noema two-phase design refreshed a repository-scoped GitHub App token for the final write, but the publication-boundary live-PR lookup still ran first with the central `.github` `github.token`. That token cannot authoritatively inspect a private sibling repository. The OIDC path also retained its pre-model exchanged token across the model call, recreating the same lifetime risk already observed for GitHub App installation tokens.

Strix has a separate live-state issue: a `repository_dispatch` can be valid when queued but refer to a PR that is closed or draft when execution begins or while a multi-hour scan is still running. Initial admission therefore cannot authorize later status publication. The scan job must suppress admission work after `should_scan=false`, and every status-publication boundary must re-read the live exact head/state/draft with fresh repository-scoped authority before writing evidence.

## Decision

1. Noema model preparation never grants predecessor evidence publication authority. After a publishable envelope exists, the selected reviewer source is refreshed before the publication-boundary live read: GitHub App mints a new repository-scoped installation token, OIDC obtains a new identity token and exchanges it for a new repository-scoped app token, and PAT remains the explicitly selected secret authority.
2. `Revalidate live Noema target before publication` and `Publish prepared Noema verdict on the exact live head` use the same selected publication-phase authority. They must not use the pre-model App/OIDC token, `github.token`, PR-author credentials, or an implicit fallback. Missing fresh authority fails closed.
3. Exact head/state/draft remain authoritative at publication time. A moved head is an error; a closed/draft exact head is resolved/non-reviewable work and produces no publication.
4. Strix propagates initial live admission through every repository-dispatch setup step so `should_scan=false` performs no target-visibility lookup, sidecar setup, scan, or status publication. After a long-running scan, the scan job refreshes repository-scoped authority and revalidates the live target immediately before its status publisher. It exports that late `publish_status` decision together with `should_scan`.
5. The separate `publish-manual-pr-evidence-status` job may start only when both `needs.strix.outputs.should_scan == 'true'` and `needs.strix.outputs.publish_status == 'true'`. Because job scheduling can itself introduce delay, that job revalidates the live exact head/state/draft again with its newly exchanged repository-scoped credential immediately before its publisher. An exact-head closed/draft target suppresses publication; a moved head or unverifiable live state fails closed.
6. Executable regressions must cover the publication-token ordering/selection, closed/draft/stale/unverifiable live states, skip propagation through target visibility, the Strix scan-job publication boundary, and the cross-job publication boundary. Completed source-fix workflows and their unique drivers are removed after the repair is materialized.

## Alternatives considered

- **Trust initial dispatch state for the full scan.** Rejected because a multi-hour security scan can outlive the reviewability of its target and then publish stale evidence.
- **Treat closed/draft as a successful security verdict.** Rejected because non-reviewable work is a no-op, not positive security evidence.
- **Publish first and reconcile stale status later.** Rejected because branch protection and schedulers can consume the stale status before cleanup.
- **Use the central repository token for cross-repository publication checks.** Rejected because it is not authoritative for private sibling targets.

## Consequences

Private sibling Noema review no longer depends on the central repository token at the publication boundary, and renewable reviewer identities are protected from long model-call expiry. Strix stops work cleanly when initial live admission says not to scan, and a PR that closes or becomes draft during a long scan cannot receive stale late status evidence. These are authority/admission corrections only; required branch-protection contexts, substantive security findings, and exact-head evidence requirements are not weakened.

This ADR remains **Proposed** until the implementation, executable regressions, and required exact-head checks are integrated on protected `main`; only then may its status advance to Accepted.
