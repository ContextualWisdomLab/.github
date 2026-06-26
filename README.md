# Contextual Wisdom Lab

Organization profile repository for **맥락지혜 연구실 / Contextual Wisdom Lab**.

The public GitHub organization profile lives in [profile/README.md](profile/README.md).

Homepage: https://contextualwisdomlab.github.io/

PR governance live audit: [PR_GOVERNANCE_AUDIT.md](PR_GOVERNANCE_AUDIT.md).
The audit includes repository-by-repository DX/UX transfer decisions: what the
central workflow borrows because it reduces friction, and what it rejects
because it adds noise or misleading review experience.

## PR review and merge policy

OpenCode judges PRs; GitHub Actions performs mechanical updates and merges.
The scheduler updates a same-repository PR branch only when the latest OpenCode
review is approved, no current-head failed check is present, and GitHub reports
the PR as behind. After that update, the new head must pass OpenCode, Strix,
required checks, and review-thread gates again before auto-merge or
`--match-head-commit` merge can proceed.
Branch updates run through the workflow `GITHUB_TOKEN`, so GitHub records those
mechanical updates as `github-actions[bot]` rather than an OpenCode app token or
a personal token. That path uses the pull-request branch update API and should
only need `pull-requests: write`; it does not justify widening repository
`contents` permission. Merge or auto-merge is a separate mutation. When a repo
wants GitHub Actions to perform the merge itself, that repo needs an explicit
scheduler-job `contents: write` policy exception and should expect Scorecard or
token-permission policy review to notice it.
That `update_branch` path is deliberately not used for `DIRTY` or
`CONFLICTING` PRs: GitHub cannot synthesize a safe conflict resolution for the
author, so the review must give the author a repair path instead of pretending
the bot can fix it.
When GitHub reports `DIRTY` or `CONFLICTING`, the scheduler does not pretend to
fix the branch. It blocks the PR with repair guidance: merge or rebase the
latest base branch into the PR branch, resolve conflict markers in that PR
branch, rerun focused checks, and push the same branch. OpenCode comments must
include a compact command block covering `gh pr checkout`, `git fetch`, merge or
rebase, `git status --short`, resolved-file staging, normal push, and
`--force-with-lease` only for rebased branches.

Strix, OpenCode, and the scheduler are sourced from the central
`ContextualWisdomLab/.github` workflows rather than copied into each repository.
Required-workflow runs execute in the target repository context, so mechanical
branch updates, stale-thread resolution, and merges use that repository's
`github-actions[bot]` token while the trusted implementation still comes from
the central repository. The scheduler dispatches same-head Strix evidence first,
then dispatches OpenCode for the same PR head when review evidence is missing or
stale.
This avoids running PR-head review, CodeGraph, coverage, or PoC code as an
unbounded local workflow copy.
Strix keeps `cancel-in-progress: false` so old evidence is not cancelled by a
force-push, but PR-scoped concurrency includes the head SHA so an obsolete scan
does not serialize newer current-head evidence.

OpenCode approval is evidence-gated. Before approval, the review summary must
name changed files, CodeGraph or structural MCP evidence, a Change Flow DAG,
100% test coverage evidence, 100% docstring coverage evidence, and a concrete
PoC/execution result. It must also split `Developer experience:` from
`User experience:` so maintainability/review/CI friction is not confused with
product, documentation, review-comment, or status-check reader outcomes. The PoC
can be a temporary scratch repro, focused test, lint, security check,
performance probe, or UI verification command, but it must be actually run and
cited. Scratch PoC files are not committed.

Failed GitHub Checks are not reviewed as URL lists. OpenCode must explain the
failed check name, failing step, source-backed file and line when available,
root cause, fix direction, and focused rerun command. Cancelled or superseded
checks must be described as queue or evidence blockers rather than invented
source-code findings.

Operational cases folded into the central policy:

- `naruon`: approved PRs can become `BEHIND`; the scheduler treats that as an
  update request, not as a merge signal. GitHub Actions updates the branch with
  `expected_head_sha`, then the new head is reviewed again.
- `pg-erd-cloud`: successful bot merges used current-head evidence and
  `--match-head-commit`; the centralized path keeps that head-SHA guard.
- `.github`: PRs that edit trusted review workflows can fail because
  `pull_request_target` runs the base branch's trusted scripts. A same-head
  manual `workflow_dispatch` Strix run may supply evidence for review, but it
  does not replace required PR checks until the trusted base branch catches up.
- `naruon#745`: new OpenCode review-flow work improves Mermaid output by
  replacing generic risk sketches with changed-file flow DAGs. The central
  workflow carries that review contract while keeping the self-test drift fix.
- Cross-repo DX/UX: helpful sibling-repo patterns should be adopted when they
  reduce maintainer, reviewer, CI-operator, contributor, user, or reader
  friction. Noisy automation, repeated waiting, false failures, misleading
  statuses, and URL-only diagnostics are treated as review-experience defects.
