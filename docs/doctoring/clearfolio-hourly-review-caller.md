# Clearfolio Hourly Review-Repair Caller Boundary

## Decision

Clearfolio's one-hour review → repair → revalidation support heartbeat is owned
by a dedicated central caller workflow,
`.github/workflows/clearfolio-hourly-review-repair.yml`. The product-neutral
engine remains `.github/workflows/pr-review-fix-scheduler.yml` and contains no
scheduled trigger or Clearfolio repository literal.

This split is an architecture decision rather than a naming preference. A
scheduled workflow executes in the repository that contains it. Letting a
central reusable workflow fall through to `github.repository` would scan
`ContextualWisdomLab/.github`, not Clearfolio, unless a mutable external variable
happened to be configured correctly. Conversely, hard-coding Clearfolio inside
the shared engine would make the reusable module misleading for naruon,
contextual-orchestrator, and other CWL services.

## Product caller

The Clearfolio caller runs at minute 23 of every hour and invokes the local
reusable workflow with explicit, reviewable values:

```yaml
target_repository: ContextualWisdomLab/clearfolio
base_branch: main
max_prs: "50"
max_dispatches: "1"
retry_hours: "1"
```

The caller and reusable engine both use `cancel-in-progress: true`. This keeps
queue inspection single-flight at the product and engine boundaries. At most one
autofix dispatch is issued during an invocation, and the same exact PR head is
not retried more than once per hour.

## Modular MSA contract

The shared workflow accepts explicit `target_repository` and `base_branch`
inputs. A sibling product may add a small schedule caller with its own exact
repository and base branch, or invoke the engine through an approved dispatch.
It does not copy the scheduler implementation, OpenCode configuration, repair
worker, or credential logic.

The shared target-selection precedence remains:

1. validated `repository_dispatch` target;
2. reusable-workflow caller input;
3. `PR_REVIEW_FIX_TARGET_REPOSITORY` repository variable;
4. the workflow execution repository.

The product-specific caller resolves the target before this fallback chain is
needed. Clearfolio therefore has a functioning default heartbeat without
changing the engine's standalone or modular semantics.

## Credential and privilege boundary

The caller passes exactly two established optional scheduler credentials:

- `PR_REVIEW_MERGE_TOKEN`;
- `OPENCODE_APPROVE_TOKEN`.

It does not use `secrets: inherit`. It does not receive
`NVIDIA_NIM_API_KEY`, because queue inspection and dispatch are not model
execution. The NVIDIA credential is bound only inside the separately reviewed
`PR Review Autofix` workflow's two OpenCode execution steps.

Both the caller and reusable scheduler keep the workflow-generated
`GITHUB_TOKEN` read-only with only `contents: read`; neither declares job-level
write elevation. Cross-repository PR inspection, acknowledgement, workflow
dispatch, and branch updates are authorized only through the explicitly mapped
`PR_REVIEW_MERGE_TOKEN` or `OPENCODE_APPROVE_TOKEN`, exposed to the scheduler as
`GH_TOKEN`. The scheduler has no `github.token` fallback. Missing credentials
therefore fail closed instead of silently broadening the workflow token.

The repair worker still cannot approve a PR, merge a PR, publish a release,
lower branch protection, or convert incomplete checks into success.

## Failure behavior

A missing cross-repository scheduler credential causes the target inspection or
dispatch to fail rather than silently changing the target to the central
repository. A missing NVIDIA credential later causes the autofix worker to fail
before model execution. Neither failure weakens independent review, security
checks, branch protection, or manual maintenance paths.

Scheduled workflows are active only from the protected default branch. The
caller is therefore not production automation while its pull request remains
unmerged. Previous feature-branch or predecessor-head runs are supporting
evidence only.

## Verification contract

Permanent tests require all of the following:

1. the Clearfolio caller contains the exact hourly cron;
2. the caller invokes the local reusable scheduler;
3. the target repository and protected base branch are explicit;
4. dispatch and retry bounds remain one;
5. caller and engine use single-flight concurrency;
6. the reusable engine contains no Clearfolio literal or scheduled trigger;
7. only the two established scheduler secrets cross the caller boundary;
8. `secrets: inherit`, `COPILOT_GITHUB_TOKEN`, and direct NVIDIA credential
   binding are absent from the caller;
9. the focused exact-head contract workflow reruns whenever the caller changes;
10. the caller and reusable scheduler retain read-only workflow-token
    permissions, declare no job-level write elevation, and contain no
    `github.token` mutation fallback.

Repository acceptance still requires current-head workflow, security,
supply-chain, automated-review, independent-review, unresolved-thread, and
branch-protection evidence.

## Rollback

Rollback removes the dedicated caller and its documentation while leaving the
reusable scheduler and reviewer credentials unchanged. A rollback must not
restore an ambiguous schedule that defaults to the central repository, add a
product literal to the shared engine, expose NVIDIA credentials to queue
inspection, replace explicit secret mapping with `secrets: inherit`, add a
`github.token` mutation fallback, or elevate the workflow-generated token.

## References (APA 7th edition)

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 5, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reusing workflows*. GitHub Docs. Retrieved August 5,
2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/how-tos/reuse-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *Workflow syntax for GitHub Actions: Jobs.<job_id>.secrets*.
GitHub Docs. Retrieved August 5, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idsecrets

GitHub, Inc. (n.d.-d). *Workflow syntax for GitHub Actions: Permissions*.
GitHub Docs. Retrieved August 5, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions
