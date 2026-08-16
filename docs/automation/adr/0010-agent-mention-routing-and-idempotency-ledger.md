# ADR-0010: Authenticated agent-mention routing with an idempotency ledger

Status: Accepted
Date: 2026-08-09
Decision owners: CWL automation maintainers

## Context

Review comments can explicitly request an approved agent, but redelivery,
edited comments, overlapping sweeps, forged bot names, and head changes can
otherwise cause duplicate or stale invocations. A comment is untrusted input;
neither visible text nor a prior automation memory proves authority.

## Decision drivers

- Exactly-once observable handling under at-least-once delivery.
- Explicit actor, repository, PR, comment, agent, and revision identity.
- No execution merely because a string resembles an agent mention.
- Recoverable evidence without a new operational database.

## Alternatives considered

1. **Dispatch every matching string.** Rejected because replay and spoofing are
   uncontrolled.
2. **Keep process-local memory.** Rejected because workers are disposable and
   concurrent.
3. **Validate live GitHub identity and persist an immutable claim/receipt in a
   bounded artifact ledger.** Selected.

## Decision

The router accepts only supported comment events or authenticated sweeps,
normalizes an exact allowlisted agent name, re-fetches the live PR/comment and
current head, and constructs an invocation key from repository, PR, comment
identity/version, requested agent, and expected head. Before dispatch it claims
that key in the GitHub-backed artifact ledger. A completed, active claim makes a
redelivery a no-op; an expired incomplete claim may be recovered with a new
attempt that links its predecessor.

Editing or deleting a comment, changing the PR head, or changing the requested
agent creates a different identity or invalidates the old request. The routed
worker receives canonical fields, never an executable string assembled from the
comment.

## Consequences

Duplicate model cost and repeated comments are bounded, and every invocation is
traceable. Artifact retention and concurrent claim races require explicit
handling; exactly-once side effects are achieved through idempotency rather than
assuming exactly-once event delivery.

## Failure and recovery

If live identity, the ledger, or dispatch is unavailable, publish no agent side
effect and retain a classified retryable receipt. Recovery re-fetches live state
and reclaims only an expired incomplete key. It never marks a failed dispatch as
completed.

## Security and governance impact

The design rejects forged identities, stale-head requests, arbitrary command
injection, and replay amplification. The router token may read comments and
write the bounded dispatch/ledger surfaces only; the invoked reviewer does not
inherit merge or branch-write authority.

## Tests and acceptance

- exact-name and near-match negative tests;
- duplicate, redelivery, edit, deletion, and head-change tests;
- concurrent claim winner/loser test;
- expired incomplete-claim recovery test;
- canonical payload and least-permission assertions; and
- protected-main receipt showing one observable invocation for one key.

## Migration and rollback

Deploy the ledger in observe-only mode, compare would-dispatch identities,
enable claims before side effects, then enable dispatch. Rollback disables new
dispatch while retaining ledger artifacts for diagnosis; it does not fall back
to unguarded string matching.

## Supersession conditions

Supersede if GitHub provides a native authenticated, idempotent agent-request
primitive with equivalent revision binding, replay protection, retention, and
audit evidence.
