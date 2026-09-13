# Explicit agent source repair

`@opencode-agent review` remains a read-only review request. Source mutation is a separate, opt-in command path:

```text
@opencode-agent fix
<specific repair instruction>
```

`repair` is an alias for `fix`. The command must be the first non-empty line and must contain a non-empty instruction. Merely mentioning `fix` or `repair` elsewhere does not grant mutation authority.

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

`.github/`, `scripts/ci/`, `.git/`, removed files, absolute/traversal paths and malformed file receipts are outside mention-mode authority. Control-plane/self-policy changes therefore require their normal repository owner path rather than an agent comment.

Before publishing, the worker verifies the resulting workspace against the sealed path snapshot, runs `git diff --check`, compiles changed Python files, repeats the live permission/comment/policy/base/head/scope validation, confirms the PR head did not move, then creates a normal commit and normal push. It never force-pushes, approves, merges, changes branch protection or weakens required checks.

A bot acknowledgement binds the exact source comment ID and body digest. A repeated sweep treats that exact acknowledged revision as already claimed. Even if acknowledgement publication fails after dispatch, worker serialization and exact-head revalidation prevent a stale later run from publishing over a moved PR head.

## Rollout and evidence

The workflow is not active for a consumer merely because central code exists. Activation requires, in order:

1. normal review and protected integration of the central `.github` implementation;
2. a protected-base consumer opt-in with a rollout-time `not_before` value;
3. an exact command on a non-protected same-repository PR head;
4. a live model-to-commit canary showing the admitted command, sealed scope, normal commit/push and the ordinary post-push required checks.

A successful review-only mention is never source-repair evidence. Source-repair progress starts only when the dedicated worker is dispatched, and completion requires an actual descendant source commit plus the repository's normal exact-head checks.
