# ADR-0011: Provider routing with per-purpose credential isolation

Status: Accepted
Date: 2026-08-09
Decision owners: CWL security and automation maintainers

## Context

Model-backed review can use NVIDIA NIM and a bounded GitHub Models fallback
pool. Provider availability and quality vary, while credentials differ in
scope, billing, rate limits, and disclosure risk. A missing optional provider
must not disable deterministic gates or cause another token to be silently
repurposed.

## Decision drivers

- Deterministic operation without optional model credentials.
- Explicit purpose and consumer for every secret.
- Bounded fallback with consistent review policy and evidence schema.
- Provider outages never synthesize approval.

## Alternatives considered

1. **One shared token for every provider and job.** Rejected due confused
   authority and blast radius.
2. **A single provider with no fallback.** Rejected for avoidable availability
   loss.
3. **Ordered candidates with provider-specific credentials, budgets, and
   normalized results.** Selected.

## Decision

NVIDIA NIM is the configured first provider for OpenCode review, followed by an
explicit allowlisted GitHub Models candidate pool. Each provider reads only its
documented secret in the job that consumes it. Candidate selection preserves
the same prompt policy, read-only tool boundary, expected-head identity,
reasoning requirements, output normalization, and total retry budget.

No credential aliasing is implicit: `NVIDIA_NIM_API_KEY`, GitHub model tokens,
App tokens, merge tokens, and `COPILOT_GITHUB_TOKEN` are distinct contracts.
Missing optional credentials skip only their provider route. Exhausting all
routes produces unavailable/failed evidence and cannot become an approval.

## Consequences

Review availability improves without conflating identities. Configuration and
cost monitoring become more complex, and provider-specific behavior needs
compatibility tests.

## Failure and recovery

Authentication, permission, integrity, TLS, schema, and policy failures fail
closed for that route and are not retried as transient transport failures.
Capacity, reset, timeout, and eligible 5xx failures may consume a bounded route
budget. Recovery rotates to another eligible provider or awaits operator repair
while deterministic work continues.

## Security and governance impact

Secret scopes, logs, artifacts, and child environments are purpose-limited.
Provider text remains untrusted advisory evidence until normalized and cannot
grant formal review, mutation, or merge authority by itself.

## Tests and acceptance

- missing-secret deterministic-path tests;
- provider order, budget, and fallback tests;
- authentication versus transient classification tests;
- secret non-propagation and log-redaction tests;
- normalized schema/head-binding parity across providers; and
- real protected-main primary and fallback canaries without secret output.

## Migration and rollback

Introduce a provider behind the candidate allowlist and canary it with a
dedicated secret. Rollback removes that candidate and secret mapping while
leaving deterministic gates and other providers unchanged.

## Supersession conditions

Supersede when provider routing, identity, cost, quality, or residency needs
require a dedicated gateway with equal or stronger credential attenuation and
evidence provenance.
