# ADR-0004 — Separate evidence and decision authorities

Status: Proposed

## Context

A green check, model verdict, COMMENTED review, source merge, or runtime execution answers a different question. Conflating these channels can create false source findings or unsafe merge conclusions.

## Alternatives

1. Collapse all green signals into one readiness flag.
2. Let automated reviewers determine merge authority.
3. Preserve independent evidence channels and compute decisions from explicit policy.

## Decision

Use option 3. Source semantic findings, infrastructure/policy blockers, checks, commit statuses, formal reviews, model judgments, merge authority, release authority, and protected-main operational acceptance remain separate.

## Consequences

Decision envelopes are more explicit and auditable. Consumers must handle `blocked` and `unknown` states without fabricating source defects.

## Failure and recovery

When evidence is stale, missing, contradictory, or unavailable, fail closed for the affected authority while continuing unrelated work.

## Security and governance

Automated/model evidence cannot impersonate qualifying independent approval. Infrastructure failures cannot gain source path/line authority merely because they block merge readiness.

## Acceptance

Tests must prove coverage/check failures do not synthesize source findings and that predecessor/status/model evidence cannot satisfy independent review requirements.

## Supersession

Supersede only with an evidence model that retains the same authority separations and auditability.