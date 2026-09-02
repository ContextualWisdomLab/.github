# Noema reviewer credential lifetime

## Incident and root cause

On 2026-09-01, trusted central Noema review for `ContextualWisdomLab/naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0` minted the repository-scoped `cwl-noema-review` GitHub App installation token before model work. Contextual-orchestrator review then exceeded the installation-token lifetime; the first later GitHub operation failed HTTP 401 and cleanup independently reported token expiry. Repository-owned deterministic checks on that Naruon head were otherwise green. The defect is in the central reviewer credential lifecycle, not Naruon product code.

A second trust-boundary defect was confirmed on 2026-09-02 while closing PR #1674 review findings: after model preparation, `Revalidate live Noema target before publication` still queried the target PR with the central `.github` workflow `github.token`, and only afterwards minted the fresh publication GitHub App token. That ordering cannot read a private sibling repository and can discard a valid prepared verdict before the fresh scoped authority exists. The OIDC path also reused its pre-model exchanged app token at publication, leaving the same long-running-review expiry class possible there.

## Closed operating contract

Noema separates model verdict preparation from GitHub publication. Preparation remains bound to the trigger's canonical exact head and the exact base commit that defined the reviewed diff/context, and stores only a bounded, owner-only, single-link runner-local envelope. If preparation intentionally skips because the PR is stale, draft, or already reviewed, the workflow emits `prepared=false` and performs no publication.

For the GitHub App path, a second repository-scoped installation token is minted only after model work and only when a publishable envelope exists. For the OIDC path, a fresh OIDC identity token is likewise exchanged for a new repository-scoped app token after model work and before any publication-boundary GitHub read. PAT remains the explicitly selected secret authority. The live publication revalidation and the final publication use the same selected publication-phase authority; neither may use the predecessor App/OIDC token, `github.token`, or the PR author. The live PR is re-fetched with that scoped authority and exact head/state/draft are validated before evidence is submitted. A base-branch advance with an unchanged PR head invalidates the prepared verdict because the changed-file diff and review context may have changed; such predecessor-base evidence is consumed without publication.

The envelope is deleted after every publication attempt, including malformed-envelope read validation failures. Executable regressions cover preparation-without-publication, exact-head/base/actor rebinding, stale heads, base drift with an unchanged head, draft skip behavior, cleanup, hard-link alias rejection, fresh App/OIDC publication authority, ordering of the refresh before the private-sibling live lookup, and the prohibition on central-token fallback.

## Verification and downstream replay

Focused CI runs the token-lifetime and two-phase handoff regressions with hash-pinned review dependencies whenever the workflow/helper/contracts change. After protected-main merge, replay unchanged `naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0` and a private sibling target: Required Noema Review must finish with current-head-and-base schema-valid review evidence or a typed review-unavailable result, never opaque expired-token 401, private-sibling lookup failure caused by the central token, or stale-head/base publication. A pre-merge run does not prove the merged workflow-source path and is not promoted to release evidence.

### Regression-suite migration

The two-phase migration also updates pre-existing executable workflow contracts to target the `Prepare Noema model verdict` step and the explicit prepare/publish helper invocations. The 2026-09-02 extension additionally requires the publication-phase App and OIDC refresh steps to precede `Revalidate live Noema target before publication`, and requires that both the revalidation and publish steps reference only the selected fresh scoped publication authority. This prevents a green focused gate from coexisting with stale broader-suite expectations for the retired single-process command, stale pre-model credentials, or the central repository token at a private-sibling publication boundary.
