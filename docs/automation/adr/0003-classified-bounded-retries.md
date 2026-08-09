# ADR-0003: Classified bounded retries

Status: Accepted
Date: 2026-08-09
Owner: CWL automation maintainers

## Context

GitHub APIs, runners, networks, and model providers can fail transiently.
Identity, authorization, integrity, TLS, policy, and source tests can also fail
permanently. Treating every failure as retryable wastes capacity, hides root
causes, repeats unsafe actions, and can publish secrets repeatedly. Treating no
failure as retryable makes ordinary service fluctuation unnecessarily
disruptive.

## Decision drivers

- Preserve correctness and security while tolerating bounded platform noise.
- Keep useful diagnostics and original failure identity.
- Prevent one failing item from monopolizing an automation run.
- Make retry behavior deterministic, testable, and observable.
- Avoid duplicate source mutation and synthetic success.

## Considered alternatives

1. Unlimited exponential retry. This can run indefinitely and amplify
   persistent or unsafe failures.
2. Retry by HTTP status alone. Provider semantics, idempotency, and integrity
   context cannot be captured by status alone.
3. Never retry. This reduces complexity but turns recoverable platform noise
   into operator work.
4. Classify failures and apply per-operation attempt and wall-clock budgets,
   idempotency, jitter, and safe fallback. This is selected.

## Decision

Only classified transient infrastructure failures and provider-capacity
failures may retry. Each operation declares maximum attempts, total wall-clock
budget, idempotency behavior, and whether a distinct configured provider or
safe read-only fallback exists. The original error and every attempt remain
attributable.

Malformed input, missing/ambiguous identity, 401/403 authority failures,
ruleset/reviewer ineligibility, checksum/signature/provenance mismatch, TLS
validation failure, unsupported payload shape, unexpected ref/head, and
product/test/security defects do not receive blind retries. They require a
material state/configuration/source change. A retry never converts missing
evidence into success, and a write is revalidated and idempotent at each
attempt.

## Consequences

Callers need explicit error taxonomies instead of broad exception loops.
Temporary capacity problems recover automatically within budget; persistent
problems surface earlier. Some false-negative classification is preferable to
an unsafe retry and can be corrected through reviewed taxonomy changes.

## Failure and recovery

When budget expires, defer the exact item with its classification, attempts,
last useful non-secret error, and next valid trigger; continue another queue
lane. A distinct provider may be tried only within the declared provider pool
and budget. After three materially different unsuccessful remedies, reassess
architecture or dependencies. Recovery reruns from a fresh snapshot, not from
an assumed in-memory state.

## Security and governance

Retry logs pass through bounded publication redaction. Credentials are not
broadened or swapped automatically after authority failure. Integrity and TLS
errors fail closed. Duplicate dispatch/mutation is constrained by idempotency
keys, writer leases, and expected-head checks.

## Verification

Tests cover each failure class, `Retry-After`, jitter bounds, attempt and time
budgets, provider exhaustion, partial publication, timeout stdout/stderr,
credential-shaped output, idempotent replay, and head movement between
attempts. Metrics distinguish attempt count from substantive completion.

## Migration and rollback

Replace broad loops incrementally with a shared classification vocabulary and
operation-specific budgets. Preserve old error evidence during comparison.
Rollback may restore a known-good bounded implementation, but cannot restore an
unbounded loop or make permanent security failures retryable.

## Supersession

This ADR is current. Provider-specific successors may refine categories and
budgets while preserving fail-closed classes, bounded attempts/time,
idempotency, diagnostics, and work-conserving deferral.
