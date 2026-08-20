# Review-agent comment invocation

Updated: 2026-08-19

## Purpose

Trusted ContextualWisdomLab maintainers can invoke the existing review planes from a pull-request conversation:

- `@cwl-noema-review` requests the independent Noema review.
- `@opencode-agent` requests a bounded current-head OpenCode review only; the invocation itself disables branch updates, automatic merge, and direct merge.

The router never checks out or executes pull-request-controlled code. It reads live PR metadata, binds the request to the current head SHA and base branch, and dispatches the already deployed central workflows in `ContextualWisdomLab/.github`.

## Architecture

GitHub organization ruleset workflows support `pull_request`, `pull_request_target`, and `merge_group`, but not `issue_comment`. Separately, an `issue_comment` workflow runs only when that workflow file exists on the commented repository's default branch. Therefore, a workflow stored only in the central `.github` repository cannot directly receive comments created in sibling repositories.

The implementation uses two bounded paths:

1. **Local fast path.** Comments on `ContextualWisdomLab/.github` trigger `issue_comment` immediately.
2. **Organization sweep.** Every five minutes, the central workflow enumerates repositories visible to its cross-repository credential, finds recently updated open PRs and recent comments, validates trusted exact mentions, and consults the central exact-name Actions artifact ledger before queuing work.

Each requested agent receives a deterministic invocation key containing the target repository, PR number, exact head SHA, base branch, requested agent, source comment ID, and requesting actor. Each agent-specific wrapper reconstructs the same canonical JSON from its validated payload, hashes it with SHA-256, and compares the result in constant time with the supplied key. Altering any bound field while retaining a syntactically valid key therefore fails closed.

The exact-name Actions artifact ledger uses `cwl-agent-invocation-<SHA-256 key>` as the artifact name. The router queries GitHub's repository artifact endpoint with the server-side exact `name` filter, validates the complete response, and treats any live exact-name artifact as durable dispatch evidence. This avoids depending on filtered workflow-run enumeration, which GitHub caps at 1,000 results even when pagination is requested.

Wrapper workflows use the verified key in their non-cancelling concurrency group, inspect the exact artifact name, and upload a 30-day immutable claim before forwarding to the authoritative review plane. Exact-key concurrency serializes duplicate wrapper runs. If a prior live claim exists, the wrapper performs no forward. If artifact visibility is delayed and a duplicate upload collides, the upload fails before the forwarding step, so the control plane fails closed rather than forwarding twice. Completed or failed authoritative work remains claimed for the retention window; a maintainer who needs a new attempt creates a new trusted source comment, which produces a distinct key.

Target-repository acknowledgement comments and reactions are user-experience signals only. They are not dispatch authority because repository writers, bot identities, or credential rotation could otherwise forge or invalidate a marker. A failed acknowledgement cannot cause completed agent work to be redispatched.

When a live claim exists without a visible receipt comment, the router republishes the acknowledgement without forwarding the request again; reaction failures are warnings and do not block the durable comment.

A user or fine-grained token enumerates organization repositories. When the OpenCode GitHub App installation token is the available credential, the sweep instead uses GitHub's installation-repositories endpoint, which returns only repositories accessible to that installation. This avoids depending on an organization-issues endpoint whose documented fine-grained token support is user-token-oriented.

This preserves the central MSA boundary without copying privileged workflow code into every product repository.

## Trust and permission boundary

- Accepted comment associations: `OWNER`, `MEMBER`, and `COLLABORATOR`.
- Bot comments, ordinary contributors, issue comments outside PRs, closed PRs, malformed metadata, and lookalike handles fail closed.
- Historical, duplicate, rejected, or already-ledgered requests do not consume the bounded new-work dispatch budget.
- The workflow default token is read-only.
- The local routing job receives job-scoped `actions: read`, `contents: write`, `issues: write`, and `pull-requests: read`.
- The organization sweep receives job-scoped `actions: read`, `contents: write`, and `id-token: write`.
- The two agent-specific wrapper workflows receive only job-scoped `actions: read` and `contents: write`; their workflow defaults remain `contents: read`.
- `actions: read` permits exact-name artifact inventory checks. Artifact upload uses the workflow artifact service and is pinned to immutable `actions/upload-artifact` v7.0.1.
- `contents: write` is intentionally retained only on jobs that call GitHub's create-repository-dispatch endpoint. GitHub documents that endpoint as requiring Contents repository permission at write level. Removing it would disable the bounded central dispatch path; broad workflow-default write access is not granted.
- The organization sweep uses the established cross-repository credential chain for reading target comments and dispatching central workflows. The local path uses that established review credential chain only for privileged `repository_dispatch`; its job-scoped `GITHUB_TOKEN` remains limited to target-repository metadata and acknowledgement UX.
- OpenCode dispatch is restricted to the exact `OPENCODE_REPOSITORY_DISPATCH_TARGETS` allowlist.
- An invocation cannot merge: `enable_auto_merge=false`, `update_branches=false`, and `merge_mode=disabled` are bound into the OpenCode invocation claim and hardcoded in the wrapper. GitHub's create-repository-dispatch endpoint allows at most 10 top-level `client_payload` properties (HTTP 422 otherwise), so those review-only constants are not copied onto the first-hop mention payload. The wrapper's merge-scheduler forward keeps the three flags that override scheduler defaults, together with repository, PR, head/base SHA, base branch, invocation key, and source comment identity.
- Every dispatch is bound to live PR number, current head SHA, base branch, source comment, requested agent, and requesting actor metadata fetched or validated immediately before dispatch.
- Router jobs use the fixed `ubuntu-24.04` runner and an immutable `actions/checkout` v7.0.1 commit pin; checkout credentials are not persisted.
- A branch-selectable `workflow_dispatch` trigger is intentionally absent. This prevents a repository writer from choosing an unreviewed branch version of the central router while the job holds dispatch permissions.

## Operator controls

- `AGENT_MENTION_LOOKBACK_HOURS`: default `168`, allowed range 1–720.
- `AGENT_MENTION_MAX_DISPATCHES`: default `20`, allowed range 1–100. The bound counts source requests that actually queue at least one new agent, not historical no-ops.
- Durable invocation claims use 30-day artifact retention. A new source comment creates a new invocation key when an intentional retry is required.
- Operators request immediate work by writing an exact trusted mention on the target pull request; otherwise, the five-minute protected-default-branch sweep processes it.
- The sweep fails visibly when no cross-repository credential is available.
- `PR_REVIEW_MERGE_TOKEN` or `OPENCODE_APPROVE_TOKEN` takes precedence. Otherwise, the workflow exchanges its OIDC token for the existing OpenCode installation token and enumerates that installation's repositories.

## Verification and rollback

The permanent quality workflow runs the deterministic router, sweep, exact-name artifact ledger, wrapper, receipt-authority, and workflow-contract suites under Python 3.14 and requires 100% production statement coverage, branch coverage, and public docstring coverage. It also compiles the Python files and checks the final diff for whitespace errors. A permanent regression contract also rejects the transient PR-specific branch-writer workflows and repair helpers used during development, so they cannot ship with the control plane.

### Activation gate

The router is inactive until its workflows and helper code are merged into the protected default branch. A materialization, predecessor, cancelled, queued, or stale-head run is not activation evidence. Production activation requires the exact final head to pass the permanent quality workflow, security and supply-chain checks, current-head automated review, an independent approval, unresolved-thread policy, and branch protection without bypass.

Rollback is deletion of the four mention-router workflows, the two Python helpers, and their focused tests. Existing Noema and OpenCode review workflows remain independently invocable and authoritative; the router does not own reviewer identity, credentials, verdict acceptance, approval, merge, or release.

## References

GitHub. (n.d.). *Available rules for rulesets*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *GITHUB_TOKEN*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/actions/concepts/security/github_token

GitHub. (n.d.). *REST API endpoints for GitHub Actions artifacts*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/rest/actions/artifacts

GitHub. (n.d.). *REST API endpoints for GitHub Actions: List workflow runs for a workflow*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-workflow

GitHub. (n.d.). *REST API endpoints for GitHub App installations*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/rest/apps/installations

GitHub. (n.d.). *REST API endpoints for issues*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/rest/issues/issues

GitHub. (n.d.). *REST API endpoints for repositories: Create a repository dispatch event*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event

GitHub. (n.d.). *Store and share data with workflow artifacts*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/actions/tutorials/store-and-share-data
