# ContextualWisdomLab central required workflow rollout

Updated: 2026-06-26 17:06 KST

## Decision

Use an organization repository ruleset instead of copying workflow files into each repository.

- Ruleset: `CWL Central required workflows`
- Ruleset ID: `18156473`
- Enforcement: `active`
- Target: branch rules on each target repository's default branch (`~DEFAULT_BRANCH`)
- Required workflow source repository: `ContextualWisdomLab/.github`
- Required workflow source repository ID: `1274066402`
- Active required workflow paths:
  - `.github/workflows/strix.yml`
  - `.github/workflows/opencode-review.yml`
- Scheduler path prepared for the same central required-workflow mechanism:
  - `.github/workflows/pr-review-merge-scheduler.yml`
- Required workflow ref: `refs/heads/main`
- Required workflow SHA: `6440d493816f8a4d66e32f2e5e8e6a9156d7f488`
- Required workflow trigger support: `pull_request_target`

This keeps Strix security evidence, OpenCode review evidence, and merge/update automation sourced from the central `.github` repository. Target repositories do not need local copies of these workflows for the organization required workflow rule.

## OpenCode required workflow posture

The central `.github/workflows/opencode-review.yml` is now part of the active organization required workflow ruleset.

- Required workflow trigger support: `pull_request_target`
- Stable required check job name: `opencode-review`
- Trusted source: `ContextualWisdomLab/.github`
- PR-head handling: checkout or fetch PR head as review data only; trusted scripts come from the central `.github` ref
- Model token posture: use the organization `STRIX_GITHUB_MODELS_TOKEN` secret for GitHub Models calls, with `github.token` as the fallback; live workflow evidence showed `github.token` alone can return 403 from `models.github.ai/inference`
- Write posture: OpenCode may create review/comment side effects through the OpenCode app token when available; `github.token` remains the last fallback and publication failures are soft-failed
- Coverage execution posture: privileged `pull_request_target` coverage runs only for same-repository PR heads; fork PR heads must be covered by an unprivileged PR-side check or manually trusted dispatch before approval
- Fork posture: PR heads are fetched through `refs/pull/<number>/head` when direct head-SHA fetch is not available, so review can inspect fork PR source as data without executing it in the trusted workflow context
- Runtime posture: pre-model failed-check evidence waits are capped at about five minutes; the later approval gate still rechecks current-head peer checks before approving

Keep the OpenCode required workflow active only while the central workflow keeps proving current-head coverage, CodeGraph initialization, bounded evidence, model review output, and approval-gate publication on the current head.

## Scheduler required workflow posture

The central `.github/workflows/pr-review-merge-scheduler.yml` now supports `pull_request_target` so it can be added to the same organization required workflow ruleset after the implementation lands on `main`.

- Required workflow trigger support: `pull_request_target`
- Stable required check job name: `scan-pr-queue`
- Trusted source: `ContextualWisdomLab/.github`
- PR-event scope: when GitHub invokes the workflow for a PR, the scheduler passes `--pr-number` and inspects only that PR instead of scanning or mutating the whole repository queue
- Token posture: the workflow passes `GH_TOKEN: ${{ github.token }}` so stale-thread resolution, branch update, auto-merge, and direct merge mutations are attributed to the target repository's `github-actions[bot]`
- Flow posture: default branches named `main` or `master` are treated as GitHub Flow; default branches named `develop` are treated as Git Flow unless a repository explicitly sets `PROJECT_FLOW`
- Automation boundary: `update-branch` handles `BEHIND` PRs only after current-head OpenCode approval; `DIRTY` or `CONFLICTING` PRs still require author or maintainer conflict resolution guidance

Do not centralize the scheduler by running a `.github` scheduled job against other repositories with the `.github` repository token. That would either fail permission checks or use the wrong mutation actor. The central path is a required workflow executed in each target repository context.

## Scope

The active ruleset targets the public, non-fork, non-archived repositories found by live GitHub inventory on 2026-06-26.

| Repository | Default branch | Flow | Open PRs | Auto-merge | Existing workflow footprint | Existing rules/protection summary |
| --- | --- | --- | ---: | --- | --- | --- |
| `ContextualWisdomLab/.github` | `main` | GitHub Flow | 25 | on | OpenCode, scheduler, Strix, Copilot | central required workflows, lock default branch |
| `ContextualWisdomLab/ContextualWisdomLab.github.io` | `main` | GitHub Flow | 9 | on | OpenCode, scheduler, Strix, Pages, Copilot | central required workflows, lock default branch |
| `ContextualWisdomLab/appguardrail` | `develop` | Git Flow | 0 | on | OpenCode, scheduler, Strix, CodeQL, release/security workflows | central required workflows, lock default branch, PR ruleset |
| `ContextualWisdomLab/bandscope` | `develop` | Git Flow | 81 | on | many CI/security workflows, OpenCode, scheduler | central required workflows, lock default branch, classic branch protection |
| `ContextualWisdomLab/clearfolio` | `main` | GitHub Flow | 18 | off | OpenCode, scheduler, Strix, CodeQL | central required workflows, PR ruleset |
| `ContextualWisdomLab/codec-carver` | `main` | GitHub Flow | 11 | on | OpenCode, scheduler, Strix, Copilot | central required workflows, lock default branch |
| `ContextualWisdomLab/contextual-orchestrator` | `main` | GitHub Flow | 0 | off | Security, Dependabot Updates | central required workflows |
| `ContextualWisdomLab/hyosung-itx-slogan-brief` | `main` | GitHub Flow | 0 | off | OpenCode, scheduler, validation, Copilot | central required workflows, no-branch-delete ruleset |
| `ContextualWisdomLab/naruon` | `develop` | Git Flow | 7 | on | CI, security scans, OpenCode, PR Governance, scheduler, Strix | central required workflows, lock default branch, PR ruleset, classic protection |
| `ContextualWisdomLab/newsdom-api` | `develop` | Git Flow | 6 | on | CI/security/release/pages workflows, OpenCode, scheduler, Strix | central required workflows, lock default branch, mirror classic protection |
| `ContextualWisdomLab/pg-erd-cloud` | `main` | GitHub Flow | 15 | on | CI/security, OpenCode, autofix/fix scheduler, scheduler, Strix | central required workflows, lock default branch |
| `ContextualWisdomLab/scopeweave` | `develop` | Git Flow | 11 | on | security scans, OpenCode, scheduler, Strix, Pages | central required workflows, lock default branch |

## Current policy

1. Security evidence, review evidence, and mechanical merge/update automation are centralized through the organization `workflows` ruleset rule.
2. The central required workflows come from `.github`; repositories should not receive copied Strix, OpenCode, or scheduler workflow files only to satisfy this rollout.
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
- `.github` PR `#77` merged the central OpenCode required-workflow path.
- `.github` PR `#77` same-head OpenCode proof run `28224085121` passed coverage evidence, CodeGraph initialization, bounded evidence preparation, model review, review comment publication, and approval-gate publication on head `59a8da0b2f56b862f6c5a0c69885f4045d6dc732`.
- `.github` PR `#77` central Strix required workflow run `28223698075` passed on the same head before merge.
- Organization ruleset `18156473` was renamed to `CWL Central required workflows` and now requires both `.github/workflows/strix.yml` and `.github/workflows/opencode-review.yml` from `.github@main` SHA `6440d493816f8a4d66e32f2e5e8e6a9156d7f488`.
- `ContextualWisdomLab/naruon` reports inherited active ruleset `18156473`, proving target-repository inheritance after the ruleset update.
- `ContextualWisdomLab/ContextualWisdomLab.github.io` PR `#25` merged the thin central scheduler caller and repository-local bootstrap fixes. Its main Strix run `28217860369` passed.
- The organization ruleset API reports the central required workflows ruleset as `active` and inherited by each public non-fork target repository.

## Good patterns to keep

- `naruon`: separates PR Governance, OpenCode review, Strix evidence, and application CI into explicit checks.
- `.github`: centralizes reusable workflow logic and review/merge scheduler code.
- `pg-erd-cloud`: has separate autofix/fix scheduler workflows, useful as a reference for repair automation but not as a merge authority.
- `ContextualWisdomLab.github.io`: thin caller pattern is acceptable for repository-local workflows only when GitHub does not offer an organization-level control. It should not be the default rollout mechanism.

## Risks and follow-up

- Existing open PRs may need a new push or base update before the newly required OpenCode check appears on their current head.
- The central Strix workflow still defaults to GPT-5 and falls back to DeepSeek models. The PR `#77` central required run passed in 9m25s, but earlier runs have been slower. If runtime or rate limits continue, adjust Strix model routing separately.
- Some repositories still have local Strix/OpenCode/scheduler workflows. Do not copy more workflows into repositories; instead, retire local copies after the organization ruleset proves the central required workflows stable on current heads.
- Some repositories use classic branch protection while others use rulesets. The next rollout pass should normalize branch protection into rulesets without removing repository-specific required application checks.
