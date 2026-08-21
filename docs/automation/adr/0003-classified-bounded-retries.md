# ADR-0003: Retry only classified transient failures within a bounded budget

Status: Accepted
Date: 2026-08-09
Decision owners: CWL reliability and security maintainers

## Context

GitHub, runners, DNS, package sources, and model providers fail transiently, but integrity, authentication, authorization, TLS, ref, schema, and product-test failures require remediation. Blind retries waste hours, obscure the first boundary, amplify provider load, and can convert unsafe or deterministic failures into misleading green outcomes.

## Decision drivers

- Recover automatically from genuine transient infrastructure faults.
- Fail quickly and closed on security, policy, identity, and source defects.
- Bound time, attempts, queue pressure, and cost.
- Preserve a concrete final diagnostic and original failure class.

## Alternatives considered

1. **Never retry.** Rejected because common network/provider transients needlessly block evidence.
2. **Retry every non-zero result.** Rejected because it hides defects and attacks, and can cause storms.
3. **Positive allowlist of transient classes with bounded attempts/backoff/total budget.** Selected.

## Decision

Each retrying operation defines accepted transient evidence, attempt count, per-attempt timeout, total budget, backoff/jitter, idempotency key, and final failure record. DNS/reset/GitHub 5xx/provider-capacity failures may qualify. Checksum/signature/pin, TLS, 401/403, OIDC, disallowed actor, malformed payload/schema, missing/moved ref, and test failures do not retry as infrastructure.

A provider retry or fallback never changes the required output schema or converts exhaustion into approval. The maintainer defers long-running/retrying work and continues other lanes.

## Consequences

Positive: fewer flaky failures without weakening fail-closed behavior. Negative: classifiers require maintenance and can be wrong; tests need realistic provider/transport fixtures.

## Failure and recovery

If classification is uncertain, fail closed and expose bounded evidence. If retry logic causes load or masks a defect, disable only that retry class, preserve the base operation, and open an incident. Exhaustion records every attempt class without secrets.

## Security and governance impact

The decision prevents retries from bypassing integrity, auth, ref, or policy boundaries and reduces denial-of-service amplification. Retry settings are reviewed source, not runtime attacker input.

## Tests and acceptance

- one positive transient class per operation;
- success after transient failure;
- exact exhaustion count and total budget;
- immediate permanent-class rejection;
- idempotent duplicate delivery; and
- final diagnostic retains first failing boundary and current revision.

## Migration and rollback

Instrument existing loops, enumerate current retry predicates, replace broad predicates with explicit classes, and add attempt receipts. Rollback returns to fail-closed single-attempt behavior, never broad retry.

## Supersession conditions

Supersede when an upstream platform provides equivalent typed, authenticated failure classes and bounded idempotent retry semantics that are verified end to end.
