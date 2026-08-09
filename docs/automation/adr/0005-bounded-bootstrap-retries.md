# ADR-0005 — Classify and bound trusted-bootstrap retries

Status: active_pr

## Context

Fleet failures show that source materialization and trusted bootstrap can fail transiently, while integrity, authorization, TLS, immutable-ref, and origin failures indicate a different security boundary.

## Drivers

Improve reliability without converting permanent or adversarial failures into green evidence. Keep retry budgets observable and finite.

## Alternatives

1. Never retry. 2. Retry every failure. 3. Retry only classified transient failures within a fixed budget.

## Decision

Choose option 3. DNS resolution, connection reset, provider capacity, and explicit rate-limit classes may retry with bounded backoff. Hash/signature, auth, TLS, ref, origin/redirect, schema, and product-test failures fail immediately.

## Consequences

Transient incidents recover without widening trust. Classifiers and budgets become part of the reviewed interface.

## Failure and recovery

On budget exhaustion, report the exact external prerequisite and defer the lane. A misclassified permanent failure reopens the incident and rolls back the classifier.

## Security and governance impact

No retry may bypass provenance, integrity, or credential checks; logs remain redacted and bounded.

## Tests and acceptance

Permanent-class negative cases must show one attempt. Transient cases prove bounded attempts, backoff, final classification, and protected-main consumer recovery.

## Migration and rollback

Introduce classifiers behind existing fail-closed behavior. Revert the classifier or disable the narrow retry path if false recovery or amplification appears.

## Supersession conditions

Supersede only with a stronger typed failure protocol that preserves finite budgets and immediate security failures.
