# ContextualWisdomLab central required workflow rollout

Updated: 2026-06-26 14:55 KST

## Decision

Use an organization repository ruleset instead of copying workflow files into each repository.

- Ruleset: `CWL Central Strix required workflow`
- Ruleset ID: `18156473`
- Enforcement: `active`
- Target: branch rules on each target repository's default branch (`~DEFAULT_BRANCH`)
- Required workflow source repository: `ContextualWisdomLab/.github`
- Required workflow source repository ID: `1274066402`
- Required workflow path: `.github/workflows/strix.yml`
- Required workflow ref: `refs/heads/main`
- Required workflow SHA: `bf516aba0abf46a5bfa095140b5ccdfa13e13a1d`
- Required workflow trigger support: `pull_request_target`

This keeps Strix security evidence centralized. Target repositories do not need local copies of the Strix workflow for this required workflow rule.

## Scope

The active ruleset targets the public, non-fork, non-archived repositories found by live GitHub inventory on 2026-06-26.

| Repository | Default branch | Flow | Open PRs | Auto-merge | Existing workflow footprint | Existing rules/protection summary |
| --- | --- | --- | ---: | --- | --- | --- |
| `ContextualWisdomLab/.github` | `main` | GitHub Flow | 25 | on | OpenCode, scheduler, Strix, Copilot | central Strix ruleset, lock default branch |
| `ContextualWisdomLab/ContextualWisdomLab.github.io` | `main` | GitHub Flow | 9 | on | OpenCode, scheduler, Strix, Pages, Copilot | central Strix ruleset, lock default branch |
| `ContextualWisdomLab/appguardrail` | `develop` | Git Flow | 0 | on | OpenCode, scheduler, Strix, CodeQL, release/security workflows | central Strix ruleset, lock default branch, PR ruleset |
| `ContextualWisdomLab/bandscope` | `develop` | Git Flow | 81 | on | many CI/security workflows, OpenCode, scheduler | central Strix ruleset, lock default branch, classic branch protection |
| `ContextualWisdomLab/clearfolio` | `main` | GitHub Flow | 18 | off | OpenCode, scheduler, Strix, CodeQL | central Strix ruleset, PR ruleset |
| `ContextualWisdomLab/codec-carver` | `main` | GitHub Flow | 11 | on | OpenCode, scheduler, Strix, Copilot | central Strix ruleset, lock default branch |
| `ContextualWisdomLab/contextual-orchestrator` | `main` | GitHub Flow | 0 | off | Security, Dependabot Updates | central Strix ruleset |
| `ContextualWisdomLab/hyosung-itx-slogan-brief` | `main` | GitHub Flow | 0 | off | OpenCode, scheduler, validation, Copilot | central Strix ruleset, no-branch-delete ruleset |
| `ContextualWisdomLab/naruon` | `develop` | Git Flow | 7 | on | CI, security scans, OpenCode, PR Governance, scheduler, Strix | central Strix ruleset, lock default branch, PR ruleset, classic protection |
| `ContextualWisdomLab/newsdom-api` | `develop` | Git Flow | 6 | on | CI/security/release/pages workflows, OpenCode, scheduler, Strix | central Strix ruleset, lock default branch, mirror classic protection |
| `ContextualWisdomLab/pg-erd-cloud` | `main` | GitHub Flow | 15 | on | CI/security, OpenCode, autofix/fix scheduler, scheduler, Strix | central Strix ruleset, lock default branch |
| `ContextualWisdomLab/scopeweave` | `develop` | Git Flow | 11 | on | security scans, OpenCode, scheduler, Strix, Pages | central Strix ruleset, lock default branch |

## Current policy

1. Security evidence is centralized through the organization `workflows` ruleset rule.
2. The central required workflow comes from `.github`; repositories should not receive copied Strix workflow files only to satisfy this rollout.
3. GitHub Flow repositories are those whose default branch is `main`.
4. Git Flow repositories are those whose default branch is `develop`.
5. OpenCode remains responsible for review judgment and structured decisions.
6. GitHub Actions remains responsible for mechanical branch updates and merges.
7. A merge is acceptable only when the current head has required checks passing, current-head OpenCode approval, no unresolved review threads, and a clean or mergeable merge state.
8. Previous-head approvals or checks are not merge evidence.

## Evidence from this rollout

- `.github` PR `#74` changed OpenCode review model order to DeepSeek R1 first and added a catalog fallback pool.
- `.github` PR `#75` removed the Strix finding against the scheduler command wrapper by using `subprocess.run(..., check=True)` and preserving the existing scrubbed failure contract.
- `.github` main Strix run `28218982899` passed after PR `#75` merged.
- `ContextualWisdomLab.github.io` PR `#25` merged the thin central scheduler caller and repository-local bootstrap fixes. Its main Strix run `28217860369` passed.
- The organization ruleset API reports the central Strix ruleset as `active` and inherited by each public non-fork target repository.

## Good patterns to keep

- `naruon`: separates PR Governance, OpenCode review, Strix evidence, and application CI into explicit checks.
- `.github`: centralizes reusable workflow logic and review/merge scheduler code.
- `pg-erd-cloud`: has separate autofix/fix scheduler workflows, useful as a reference for repair automation but not as a merge authority.
- `ContextualWisdomLab.github.io`: thin caller pattern is acceptable for repository-local workflows only when GitHub does not offer an organization-level control. It should not be the default rollout mechanism.

## Risks and follow-up

- OpenCode is not yet enforced as an organization required workflow because the current central `OpenCode Review` workflow is `workflow_dispatch` only. A required workflow must use a supported PR or merge trigger.
- The central Strix workflow still defaults to GPT-5 and falls back to DeepSeek models. It passed, but the post-merge run took 21m39s. If runtime or rate limits continue, adjust Strix model routing separately.
- Some repositories still have local Strix/OpenCode/scheduler workflows. Do not copy more workflows into repositories; instead, decide which local files can be retired after the organization ruleset has proven stable.
- Some repositories use classic branch protection while others use rulesets. The next rollout pass should normalize branch protection into rulesets without removing repository-specific required application checks.

