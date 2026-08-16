# ADR-0006: Operational incidents close on protected-main or real-consumer evidence

Status: Accepted
Date: 2026-08-09
Decision owners: CWL reliability and product maintainers

## Context

Feature-branch tests prove source behavior in a development context. Central workflows, required-workflow sourcing, rulesets, dispatch permissions, secrets, provider integration, and product consumers may behave differently after merge. Several incidents recurred because source integration was treated as operational closure.

## Decision drivers

- Verify the exact integrated source and deployed GitHub configuration.
- Catch base-branch sourcing, credential, event, and consumer-contract failures.
- Keep closure scenario-specific and reopenable.
- Produce evidence buyers and operators can audit.

## Alternatives considered

1. **Close on local tests.** Rejected because it misses hosted integration.
2. **Close when the PR merges.** Rejected because merge does not prove runtime activation.
3. **Require protected-main central proof and, for consumer-facing changes, a real low-risk consumer positive/negative canary.** Selected.

## Decision

Every operational incident names an acceptance scenario before repair. After protected merge, run the scenario against the integrated commit and capture repository, workflow source, source/base identity, run/attempt, outcome, and rollback result. Central reusable/required workflow changes additionally run a real product-repository consumer and relevant negative control.

An `operational_acceptance` record closes only the named incident/scenario. Contradictory live evidence reopens it.

## Consequences

Positive: fewer paper fixes and stronger acquisition/audit evidence. Negative: closure takes longer and depends on safe canary availability and provider/platform health.

## Failure and recovery

If protected-main or consumer proof fails, reopen the incident, classify whether source, configuration, permissions, provider, or consumer caused the failure, and continue the normal test-first loop. Do not roll back unrelated gates or declare the consumer out of scope after the fact.

## Security and governance impact

Operational proof confirms real authority, secret, and trust-boundary behavior without bypass. Canaries use low-risk classified data and least privilege.

## Tests and acceptance

- source PR exact-head gate;
- protected-main workflow source receipt;
- real consumer positive path;
- relevant negative control (missing policy/secret, stale head, unsafe content, or provider failure);
- rollback or deterministic rehearsal; and
- dated traceability entry.

## Migration and rollback

Add acceptance criteria to incident issues/PRs, then index existing high-risk central repairs as evidence becomes available. If no safe real canary exists, keep the incident open or feature inactive rather than inventing evidence.

## Supersession conditions

Supersede when continuous verified deployment automatically binds protected source, configuration, consumer, negative control, and rollback evidence with equivalent auditability.
