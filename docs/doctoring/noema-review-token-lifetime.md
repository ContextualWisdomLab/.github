# Noema reviewer credential lifetime

## Incident and root cause

On 2026-09-01, trusted central Noema review for `ContextualWisdomLab/naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0` minted the repository-scoped `cwl-noema-review` GitHub App installation token before model work. Contextual-orchestrator review then exceeded the installation-token lifetime; the first later GitHub operation failed HTTP 401 and cleanup independently reported token expiry. Repository-owned deterministic checks on that Naruon head were otherwise green. The defect is in the central reviewer credential lifecycle, not Naruon product code.

## Closed operating contract

Noema separates model verdict preparation from GitHub publication. Preparation remains bound to the trigger's canonical exact head and the exact base commit that defined the reviewed diff/context, and stores only a bounded, owner-only, single-link runner-local envelope. If preparation intentionally skips because the PR is stale, draft, or already reviewed, the workflow emits `prepared=false` and performs no publication.

For the GitHub App path, a second repository-scoped installation token is minted only after model work and only when a publishable envelope exists. Publication never reuses the predecessor App token, never falls back to `github.token` or the PR author, and independently re-fetches the live PR/head/base and reviewer actor before submitting evidence. A base-branch advance with an unchanged PR head invalidates the prepared verdict because the changed-file diff and review context may have changed; such predecessor-base evidence is consumed without publication. PAT and OIDC remain explicit sources: publication uses only the selected source and fails closed if it is absent; this repair does not silently convert those paths to another authority.

The envelope is deleted after every publication attempt, including malformed-envelope read validation failures. Executable regressions cover preparation-without-publication, exact-head/base/actor rebinding, stale heads, base drift with an unchanged head, draft skip behavior, cleanup, and hard-link alias rejection. Step-scoped workflow regressions prove that the second App mint sits between preparation and publication and that publication references the fresh token.

## Verification and downstream replay

Focused CI runs the token-lifetime and two-phase handoff regressions with hash-pinned review dependencies whenever the workflow/helper/contracts change. After protected-main merge, replay unchanged `naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0`: Required Noema Review must finish with current-head-and-base schema-valid review evidence or a typed review-unavailable result, never opaque expired-token 401 and never stale-head/base publication. A pre-merge run does not prove the merged workflow-source path and is not promoted to release evidence.

### Regression-suite migration

The two-phase migration also updates pre-existing executable workflow contracts to target the `Prepare Noema model verdict` step and the explicit prepare/publish helper invocations. This prevents a green focused gate from coexisting with stale broader-suite expectations for the retired single-process command or step name.
