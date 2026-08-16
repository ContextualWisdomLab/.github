# ADR-0002: Bind evidence to exact source head and independently resolved live base

Status: Accepted
Date: 2026-08-09
Decision owners: CWL repository maintainers

## Context

GitHub exposes a PR head, a base SHA captured in PR metadata, synthetic merge commits, live branch refs, checks, statuses, reviews, workflow runs, and artifacts. These identities can diverge. Earlier operational incidents showed that a green predecessor, synthetic merge, or stale base snapshot can be misrepresented as current source evidence.

## Decision drivers

- Prove exactly what source was tested and reviewed.
- Detect compatibility drift when the protected base advances.
- Preserve useful synthetic-merge evidence without mislabeling it.
- Make all write and merge operations race-safe.

## Alternatives considered

1. **Trust PR API `base.sha` and `head.sha` once per run.** Rejected because the live base and head may move after observation.
2. **Use only GitHub's synthetic merge SHA.** Rejected because it obscures the source commit and may not exist or match required source-head review.
3. **Track source head, PR base snapshot, independently resolved live base, workflow source, run/attempt, and merge revision separately.** Selected.

## Decision

All checks, reviews, statuses, artifacts, findings, and mutations name the immutable `source_revision`. Decision time independently resolves the protected base ref into `live_base_revision` and keeps the PR metadata base as historical `base_revision_snapshot`. Trusted workflow source SHA and Actions run/attempt are separate identities.

Any source-head movement invalidates predecessor-head evidence. Any live-base movement triggers compatibility re-evaluation under repository policy. Synthetic merge and merge-group evidence remain labeled and cannot silently replace source-head proof. Mutations use expected-head semantics.

## Consequences

Positive: evidence is auditable and stale success cannot authorize a merge. Negative: more API calls and evidence fields are required; a moving base can regenerate costly checks.

## Failure and recovery

On mismatch, abort the mutation, mark evidence stale, refresh the PR/head/base/workflow state, and rerun only the gates required for the new identity. Do not transplant review text or run URLs into a current-head claim.

## Security and governance impact

This decision prevents stale-evidence spoofing, review replay, and TOCTOU writes. It supports ruleset and last-push review semantics but does not weaken GitHub's native interpretation.

## Tests and acceptance

- source head versus synthetic merge fixtures;
- live base advancing after PR snapshot;
- workflow SHA and run-attempt artifact identity;
- stale formal review/status/check rejection;
- expected-head update/merge failure; and
- protected-main acceptance naming the integrated SHA.

## Migration and rollback

Add identity fields to payloads and results compatibly, update consumers, then make validation mandatory. Rollback may disable an optional consumer but must not return to a single ambiguous `sha` field.

## Supersession conditions

Supersede only if GitHub exposes one cryptographically bound, policy-authoritative evidence object that simultaneously and unambiguously identifies source, current base, workflow source, run attempt, review, and merge context.
