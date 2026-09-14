# Source-fix command lane

CWL review mentions and source mutation are separate capabilities. `@opencode-agent` remains a review request. A maintainer who needs an agent to change an existing pull-request branch uses the explicit source-fix lane instead:

```text
@cwl-source-fix Fix the stale selection state that is lost after project reload. Preserve the existing persistence contract and add the smallest regression-safe repair.
```

For compatibility, `@opencode-agent fix ...` and `@opencode-agent repair ...` are also recognized by the source-fix sweep. Those compatibility forms still match the review mention router, so they can enqueue a review as well. Use `@cwl-source-fix` when source mutation is the only requested action.

## Trust and mutation boundary

The command is accepted only from an `OWNER`, `MEMBER`, or `COLLABORATOR` on an open same-repository pull request in the configured OpenCode repository allowlist. The invocation is bound to the requesting actor, source comment ID, repository, pull-request number, base ref/SHA, and head ref/SHA. A durable exact-name Actions artifact prevents the same immutable invocation from being applied twice.

The worker deliberately rejects `ContextualWisdomLab/.github`. Central automation cannot use this lane to rewrite its own control plane. It also excludes `.github/` and `scripts/ci/` paths in target repositories. Control-plane repairs stay with the canonical `.github` development path rather than being delegated to a source-fix command.

The editable set comes from the complete paginated GitHub PR Files receipt. The `changed_files` count must match the returned records and may not exceed GitHub's 3,000-file PR Files ceiling. Removed, unsafe, control-plane, or non-PR-authored paths are excluded. Version 1 cannot add a new path or broaden the pull request's authored scope.

## Execution model

The scheduled sweep rotates across accessible CWL repositories and looks only for trusted source-fix commands. It dispatches an exact immutable claim to the central worker. Before editing, the worker re-reads the live pull request and source comment, verifies the same actor and command, rejects fork heads, and checks that the base/head tuple has not moved.

OpenCode runs through the released contextual-orchestrator sidecar with `contextual-orchestrator/orchestrator/free`. Provider-specific models and paid fallback are not selected by this workflow. Shell, web, external-directory, task, and nested-agent access are denied to the model. The maintainer's requested outcome is treated as untrusted task text, not as permission to weaken tests, review gates, security boundaries, or repository policy.

The pre-edit workspace is snapshotted, the temporary OpenCode configuration is restored before scope verification, and every changed path must remain inside the sealed PR-authored allowlist. The worker runs `git diff --check`, compiles changed Python files, and runs `actionlint` for changed workflows when available. Immediately before mutation it re-reads the live PR head. Only an unchanged exact head may receive a normal descendant commit and non-force push.

A successful source-fix run does not approve or merge the pull request. The new head must pass the repository's normal checks, security scans, and independent review. If the model cannot make a safe in-scope change, the tree remains unchanged. Because the invocation ledger is comment-scoped, a materially new repair request should be made in a new comment rather than editing or replaying the old command.
