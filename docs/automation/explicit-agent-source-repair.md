# Explicit agent source repair

`@opencode-agent`, `@noema-agent`, and `@strix-agent` remain review-only handles. Source mutation uses a separate opt-in command:

```text
@cwl-source-fix
<specific repair instruction>
```

The command must be the first non-empty line and must contain a non-empty instruction, either on that line after `:`/`-` or on following lines. Appending `fix` or `repair` to a review-agent mention does not grant mutation authority and is not source-repair progress.

## Trust and admission

The central `.github` repository owns the control plane. The source-repair sweep observes recent pull-request comments with the OpenCode GitHub App token, then revalidates every candidate before dispatch:

- the pull request is still open and its head is in the same repository;
- base ref/SHA and head ref/SHA still match the command's exact admission envelope;
- the head branch is not protected;
- the commenter is human, still has `write` or `admin` permission, and the exact comment body SHA-256 has not changed;
- edited comments are rejected;
- the protected base contains `.github/cwl-agent-source-repair.json` with version `1`, `enabled: true`, and a timezone-aware `not_before` timestamp;
- the command timestamp is on or after `not_before`, so enabling the feature cannot retroactively execute old comments;
- the paginated GitHub PR Files receipt is complete and agrees with the live `changed_files` count.

A consumer opt-in file is intentionally simple:

```json
{
  "version": 1,
  "enabled": true,
  "not_before": "2026-09-14T00:00:00Z"
}
```

Choose `not_before` at rollout time on the protected base. Absence, malformed JSON, an unsupported version, extra fields, or `enabled: false` fails closed.

## Mutation boundary

The writer is serialized per target repository and pull request. It checks out the admitted exact head, uses only `contextual-orchestrator/orchestrator/free`, and runs OpenCode with shell, web, task, external-directory and credential access denied. It may edit only the complete safe current-PR path set sealed by the control plane.

`.github/`, `scripts/ci/`, `.git/`, removed files, absolute/traversal paths and malformed file receipts are outside source-fix authority. Control-plane/self-policy changes therefore require their normal repository owner path rather than an agent comment.

Before publishing, the worker verifies the resulting workspace against the sealed path snapshot, runs `git diff --check`, compiles changed Python files in isolated interpreter mode with bytecode written outside the target workspace, parses every changed `.yml`/`.yaml` file before publication, repeats the live permission/comment/policy/base/head/scope validation, confirms the PR head did not move, verifies every staged path against the sealed path list after staging, then creates a normal commit and normal push. A malformed model-edited YAML file therefore cannot become the source-repair commit merely because its path was authorized. The worker never force-pushes, approves, merges, changes branch protection or weakens required checks.

A durable bot claim binds the exact source comment ID and body digest before dispatch. If publishing that claim fails, no worker is enqueued. A repeated sweep treats that exact claimed revision as already claimed even when the PR head moves. If dispatch fails after the claim is stored, the command remains claimed and is not automatically replayed; an operator must inspect the failure and issue a new explicit command rather than retrying the old revision.

## Rollout and evidence

The workflow is not active for a consumer merely because central code exists. Activation requires, in order:

1. normal review and protected integration of the central `.github` implementation;
2. a protected-base consumer opt-in with a rollout-time `not_before` value;
3. an exact `@cwl-source-fix` command on a non-protected same-repository PR head;
4. a live model-to-commit canary showing the admitted command, sealed scope, normal commit/push and the ordinary post-push required checks.

A successful review-only mention is never source-repair evidence. Source-repair progress starts only when the dedicated mutation command reaches the write-capable worker, and completion requires an actual descendant source commit plus the repository's normal exact-head checks.
