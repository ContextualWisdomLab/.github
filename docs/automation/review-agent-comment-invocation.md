# Review-agent comment invocation

Updated: 2026-08-05

## Purpose

Trusted ContextualWisdomLab maintainers can invoke the existing review planes from a pull-request conversation:

- `@cwl-noema-review` requests the independent Noema review.
- `@opencode-agent` requests a bounded current-head OpenCode review only; the invocation itself disables branch updates, automatic merge, and direct merge.

The router never checks out or executes pull-request-controlled code. It reads live PR metadata, binds the request to the current head SHA and base branch, and dispatches the already deployed central workflows in `ContextualWisdomLab/.github`.

## Architecture

GitHub organization ruleset workflows support `pull_request`, `pull_request_target`, and `merge_group`, but not `issue_comment`. Separately, an `issue_comment` workflow runs only when that workflow file exists on the commented repository's default branch. Therefore, a workflow stored only in the central `.github` repository cannot directly receive comments created in sibling repositories.

The implementation uses two bounded paths:

1. **Local fast path.** Comments on `ContextualWisdomLab/.github` trigger `issue_comment` immediately.
2. **Organization sweep.** Every five minutes, the central workflow enumerates repositories visible to its cross-repository credential, finds recently updated open PRs and recent comments, validates trusted exact mentions, and dispatches unacknowledged requests. A hidden receipt keyed by source comment ID prevents normal repeated sweeps or local workflow reruns from redispatching the same invocation.

A user or fine-grained token enumerates organization repositories. When the OpenCode GitHub App installation token is the available credential, the sweep instead uses GitHub's installation-repositories endpoint, which returns only repositories accessible to that installation. This avoids depending on an organization-issues endpoint whose documented fine-grained token support is user-token-oriented.

This preserves the central MSA boundary without copying privileged workflow code into every product repository.

## Trust and permission boundary

- Accepted comment associations: `OWNER`, `MEMBER`, and `COLLABORATOR`.
- Bot comments, ordinary contributors, issue comments outside PRs, closed PRs, malformed metadata, already acknowledged comments, and lookalike handles fail closed.
- The workflow default token is read-only.
- The local job receives job-scoped `contents: write`, `issues: write`, and `pull-requests: read`.
- The organization sweep uses the established cross-repository credential chain for reading and acknowledging target comments, while the central repository's own token dispatches the central workflows.
- OpenCode dispatch is restricted to the exact `OPENCODE_REPOSITORY_DISPATCH_TARGETS` allowlist.
- An invocation cannot merge: `enable_auto_merge=false`, `update_branches=false`, and `merge_mode=disabled` are explicit in the dispatch payload.
- Every dispatch is bound to live PR number, current head SHA, and base branch metadata fetched from GitHub immediately before dispatch.

## Operator controls

- `AGENT_MENTION_LOOKBACK_HOURS`: default `168`, allowed range 1–720.
- `AGENT_MENTION_MAX_DISPATCHES`: default `20`, allowed range 1–100.
- Manual `workflow_dispatch` supports the same bounds and a dry-run mode.
- The sweep fails visibly when no cross-repository credential is available.
- `PR_REVIEW_MERGE_TOKEN` or `OPENCODE_APPROVE_TOKEN` takes precedence. Otherwise, the workflow exchanges its OIDC token for the existing OpenCode installation token and enumerates that installation's repositories.

## References

GitHub. (n.d.). *Available rules for rulesets*. GitHub Docs. Retrieved August 5, 2026, from https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August 5, 2026, from https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *REST API endpoints for GitHub App installations*. GitHub Docs. Retrieved August 5, 2026, from https://docs.github.com/en/rest/apps/installations

GitHub. (n.d.). *REST API endpoints for issues*. GitHub Docs. Retrieved August 5, 2026, from https://docs.github.com/en/rest/issues/issues
