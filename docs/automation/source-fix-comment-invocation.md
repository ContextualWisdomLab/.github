# Source-fix comment invocation

`@opencode-agent`, `/opencode`, `/oc`, and `@cwl-noema-review` remain review requests. Appending words such as `fix` or `repair` to those handles does not grant repository mutation authority.

A maintainer who explicitly wants the central automation plane to repair the current pull-request source can use a separate command in that PR conversation:

```text
@cwl-source-fix <concrete repair instruction>
```

The command is deliberately narrower than a general coding agent. The router accepts only an open ContextualWisdomLab pull request and an OWNER, MEMBER, or COLLABORATOR comment. The mutation worker then re-fetches the requester’s current repository permission and requires `write`, `maintain`, or `admin`; re-fetches the source comment and verifies its full SHA-256 digest; and verifies the exact live base/head refs and SHAs before checking out anything.

The authenticated GitHub pull-request Files API is the mutation scope. Pagination must be complete and its record count must equal the PR’s live `changed_files` count. The model may edit only non-removed paths already present in that current PR diff. A source fix cannot add a new concern to the PR, create an unrelated file, change a different branch, approve the PR, merge the PR, or weaken a gate. A moved head, edited/deleted command, stale base, incomplete file receipt, revoked permission, out-of-scope edit, or unavailable write credential fails closed.

Model execution uses only `contextual-orchestrator/orchestrator/free` through the central contextual-orchestrator sidecar. GitHub and OIDC credentials are removed from the model process. Shell, external-directory, web, task, and skill permissions are denied. After editing, the worker checks the changed-path set against the sealed PR-file receipt, runs `git diff --check`, compiles changed Python files, parses changed YAML files, revalidates the live head again, and only then pushes one ordinary commit to the existing PR branch. Normal exact-head CI and independent review remain authoritative after that push.

The central invocation identity binds repository, PR number, requester, source comment ID, complete instruction digest, base/head refs and SHAs, and the fixed `existing-pr-files-only` write mode. A durable exact-name Actions artifact prevents the same immutable request from being applied twice. The scheduled organization sweep exists because sibling-repository `issue_comment` events do not reach the central repository directly; it uses the same parser, identity claim, permission boundary, and worker as the local path.
