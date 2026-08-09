# ADR-0001: Writer lease and read-only fleet auditor

Status: Accepted
Date: 2026-08-09
Owner: CWL automation maintainers

## Context

The control plane can review, repair, update, and merge across many
repositories. Scheduled automation, review callbacks, autofix workers, and
maintainers can observe the same branch concurrently. Without an explicit
ownership rule, two actors can race, overwrite a valid repair, publish evidence
for different heads, or let a stale worker cancel current work. Fleet audit has
organization-wide breadth, which would magnify the impact if its credential
were also allowed to mutate source.

## Decision drivers

- Preserve contributor work and exact-head evidence.
- Allow concurrency across independent repositories and branches.
- Keep organization-wide inspection low impact and least privilege.
- Make lease loss and stale state observable and recoverable.
- Avoid a centralized lock service unless GitHub-native controls prove
  insufficient.

## Considered alternatives

1. Serialize the whole organization. This is safe but creates unnecessary
   head-of-line blocking and violates work conservation.
2. Let each workflow write optimistically and repair conflicts. This permits
   stale or duplicate mutations and makes review evidence ambiguous.
3. Give the fleet auditor the writer credential for convenience. This creates
   a high-impact cross-repository authority path.
4. Use a logical branch-scoped lease backed by GitHub concurrency, live ref
   validation, expected-head guards, and explicit handoff. This fits current
   infrastructure and allows independent lanes.

## Decision

Exactly one actor may hold source-write ownership for `(repository, branch)` at
a time. The holder records target identity, purpose, run, observed head, and
lease generation; it re-fetches PR/ref/base/review state immediately before
each mutation. A head mismatch, conflicting source-affecting action, lost
concurrency ownership, or invalid handoff ends write authority for that run.

GitHub workflow concurrency and the scheduler's live-head/expected-head guards
implement partial per-workflow race controls. They do not form one distributed
lease across merge, autofix, rebase, and other writers. A dedicated owner,
TTL/heartbeat, fencing generation, and takeover record is tracked in
`ContextualWisdomLab/.github#890`. Different repositories/branches and
read-only work may run concurrently. The fleet auditor uses a credential and
workflow role that cannot dispatch mutation, publish formal approval, push,
merge, release, or deploy.

## Consequences

Throughput scales by independent branch rather than by organization. A stale
worker may finish computation but cannot publish authoritative mutation for a
new head. Each write path needs repeated live validation and deterministic
lease-key construction. Handoffs are more explicit, and duplicate work can
still occur before the final guarded mutation.

## Failure and recovery

On contention, defer the losing item with its exact target and continue another
lane. On lease loss or head movement, discard mutation intent, retain bounded
diagnostics, and rebuild evidence for the new snapshot. If the lease mechanism
itself is inconsistent, freeze only the affected mutation class; preserve
read-only audit. Recover through a reviewed change and verify one competing
worker scenario plus a real consumer.

## Security and governance

Lease ownership does not grant review, merge, release, or deployment authority.
The holder still needs the correct job-scoped credential and every external
rule. Auditor credentials remain read-only even during an incident. Protected
branch history is never force-rewritten to repair lease failure.

## Verification

Tests cover two writers selecting the same head, head movement before push,
safe concurrency on distinct branches, stale cancellation, idempotent replay,
lease handoff, and an auditor attempting a write. The final GitHub action must
show expected-head protection. Fleet audit verifies no mutation permissions.

## Migration and rollback

Every writer adopts the common lease key and pre-mutation revalidation. Existing
workflow concurrency/live-head guards remain in force during migration.
Rollback disables the new writer path or reverts to the last known-good guarded
path; it does not disable branch protection. Introduce external lease storage
only with a new ADR and dual-read validation plan.

## Supersession

This ADR is current. A future ADR may replace the GitHub-native distributed
lease with a persisted lease service, but must retain branch scope, lease loss,
head guards, read-only audit, migration, and rollback semantics.
