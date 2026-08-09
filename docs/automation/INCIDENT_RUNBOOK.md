# Automation control-plane incident runbook

Status: active_pr

## 1. Establish current identity

Refetch repository policy, protected base ref, PR source head, target blobs/refs, workflow source revision, requested/formal reviews, unresolved threads, statuses, runs/jobs, and writer state. Record source head and live base as separate values.

## 2. Find the first failing boundary

Separate symptom, immediate cause, root cause, and owner. Classify the boundary as source/test, trusted bootstrap/materialization, workflow contract, runner/provider, credential/permission, reviewer/governance, concurrency/queue, or protected-main runtime.

## 3. Test remedies for feasibility

Enumerate materially distinct minimal remedies. Reject any remedy that needs invented credentials or reviewers, weakens a gate, uses stale evidence, races a writer, changes unrelated behavior, or lacks an observable acceptance test and rollback.

## 4. Retry classification

Retry only evidence-classified transient DNS/connectivity, rate-limit, or provider-capacity failures within a bounded budget. Do not retry integrity/hash/signature, authorization, TLS/certificate, immutable ref, untrusted origin/redirect, schema, or product-test failures as infrastructure noise.

## 5. Execute and verify

Implement the smallest root-cause-changing repair test-first. Refetch immediately before each write and use CAS/blob/ref-bound or non-force fast-forward mutation. Verify the exact resulting head with deterministic, security, dependency, and automated-review evidence.

## 6. Protect queue health

Defer the exact pending identity after one read. Preserve the sole current-head evidence lane and cancel only runs proven obsolete by current PR/head/workflow identity. Interactive dispatch and scheduled sweeps use isolated concurrency so a sweep cannot replace interactive work.

## 7. Merge and operational acceptance

Merge only after actual protection and counted independent exact-head approval pass. For operational defects, exercise the protected-main scheduled/manual consumer, verify downstream acknowledgement and negative control, and rehearse rollback before closure.

## 8. Reopen conditions

Reopen when the same failure class recurs, the protected-main consumer did not execute the repaired boundary, evidence was stale/synthetic, rollback was not viable, or a security control was weakened to obtain green status.
