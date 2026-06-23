# Contextual Wisdom Lab

Organization profile repository for **맥락지혜 연구실 / Contextual Wisdom Lab**.

The public GitHub organization profile lives in [profile/README.md](profile/README.md).

Homepage: https://contextualwisdomlab.github.io/

PR governance live audit: [PR_GOVERNANCE_AUDIT.md](PR_GOVERNANCE_AUDIT.md).

## PR review and merge policy

OpenCode judges PRs; GitHub Actions performs mechanical updates and merges.
The scheduler updates a same-repository PR branch only when the latest OpenCode
review is approved and GitHub reports the PR as behind. After that update, the
new head must pass OpenCode, Strix, required checks, and review-thread gates
again before auto-merge or `--match-head-commit` merge can proceed.
Branch updates and merges run through the workflow `GITHUB_TOKEN`, so GitHub
records those mechanical mutations as `github-actions[bot]` rather than an
OpenCode app token or a personal token.

OpenCode review execution is `workflow_dispatch`-only. The scheduler dispatches
same-head Strix evidence first, then dispatches OpenCode for the same PR head.
This avoids running PR-head review, CodeGraph, coverage, or PoC code from a
privileged `pull_request_target` OpenCode workflow.

OpenCode approval is evidence-gated. Before approval, the review summary must
name changed files, CodeGraph or structural MCP evidence, a Change Flow DAG,
100% test coverage evidence, 100% docstring coverage evidence, and a concrete
PoC/execution result. The PoC can be a temporary scratch repro, focused test,
lint, security check, performance probe, or UI verification command, but it must
be actually run and cited. Scratch PoC files are not committed.

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
