# ADR-0014: Metadata-only privileged events with default-branch dispatch

Status: Accepted
Date: 2026-08-09
Decision owners: CWL security and workflow maintainers

## Context

`pull_request_target` supplies a trusted base-repository context and can reach
secrets or write permissions, while PR filenames, refs, source, artifacts, and
comments are attacker-controlled. Review and autofix still need bounded PR data
and, in some paths, privileged publication or mutation.

## Decision drivers

- Untrusted PR code never executes with privileged event authority.
- Stable required contexts still materialize for fork and same-repository PRs.
- Privileged workers execute immutable protected-default-branch source.
- Every dispatch is rebound to live repository/PR/revision identity.

## Alternatives considered

1. **Checkout and run the PR from `pull_request_target`.** Rejected due direct
   secret and repository compromise risk.
2. **Use only unprivileged `pull_request`.** Rejected because trusted
   publication/organization coordination and stable fork handling are limited.
3. **Metadata-only privileged entrypoint plus authenticated default-branch
   dispatch and bounded PR-data materialization.** Selected.

## Decision

Privileged PR events may read and validate metadata and materialize stable check
contexts, but MUST NOT check out or execute PR-controlled code, actions,
containers, package hooks, or shell text. Work requiring trusted publication or
mutation is sent through an allowlisted `repository_dispatch` payload to a
workflow loaded from the protected default branch.

The receiver validates triggering actor and sender, target allowlist, event
schema, open PR state, base/head repository, refs and SHAs, mutability, and live
GitHub identity before reading PR source as inert data or running it inside an
explicit low-privilege sandbox. Any mismatch fails before a secret/write step.

## Consequences

The primary secret-execution boundary is reviewable and reusable across
repositories. Workflows become more complex and need payload compatibility,
idempotency, and two-stage observability.

## Failure and recovery

Missing actor configuration, malformed payload, unavailable live metadata, or
identity movement fails closed. Recovery creates a fresh dispatch from current
live state; it never edits the old payload or broadens the privileged event.

## Security and governance impact

PR content remains untrusted across filenames, archives, symlinks, artifacts,
logs, prompts, and commands. OIDC/App and mutation credentials exist only in the
specific protected-source job that needs them and are not inherited by PR
execution.

## Tests and acceptance

- workflow contract rejects PR checkout/execution in privileged entrypoints;
- actor/target/schema/base/head mismatch negative tests;
- fork/external-head and symlink/archive adversarial tests;
- least-permission and secret-environment assertions; and
- protected-main positive/negative dispatch canary with exact-head receipt.

## Migration and rollback

Move executable privileged steps behind a default-branch dispatcher, add live
binding tests, then remove them from the event workflow. Rollback disables the
dispatch or reverts its protected implementation; it never restores privileged
PR-head execution.

## Supersession conditions

Supersede if GitHub provides a native primitive that combines immutable trusted
workflow source, attenuated identity, exact PR revision binding, fork support,
and equivalent audit evidence without `pull_request_target` dispatch.
