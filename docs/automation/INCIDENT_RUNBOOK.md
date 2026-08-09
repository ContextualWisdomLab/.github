# Automation control-plane incident runbook

Status: active_pr

## 1. Establish current identity

Refetch repository policy, protected base ref, PR source head, target blobs/refs, workflow source revision, requested/formal reviews, unresolved threads, statuses, runs/jobs, external scheduler/automation writer state, canonical documentation owner, and writer lease. Record source head and live base as separate values.

## 2. Find the first failing boundary

Separate symptom, immediate cause, root cause, and owner. Classify the boundary as source/test, trusted bootstrap/materialization, workflow contract, external scheduler/continuation, runner/provider, credential/permission, reviewer/governance, concurrency/queue, documentation authority, or protected-main runtime.

For an early-stop symptom, prove whether another safe lane was executable at termination. If yes, the root cause is the prompt/control rule that incorrectly promoted an intermediate event to terminal, not the blocked PR/check/review itself.

## 3. Test remedies for feasibility

Enumerate materially distinct minimal remedies. Reject any remedy that needs invented credentials or reviewers, weakens a gate, uses stale evidence, races a writer, changes unrelated behavior, creates a parallel documentation authority, or lacks an observable acceptance test and rollback.

## 4. Retry classification

Retry only evidence-classified transient DNS/connectivity, rate-limit, or provider-capacity failures within a bounded budget. Do not retry integrity/hash/signature, authorization, TLS/certificate, immutable ref, untrusted origin/redirect, schema, product-test, or deterministic continuation-contract failures as infrastructure noise.

## 5. Execute and verify

Implement the smallest root-cause-changing repair test-first. Refetch immediately before each write and use CAS/blob/ref-bound or non-force fast-forward mutation. Verify the exact resulting head with deterministic, security, dependency, automated-review, documentation-fitness, and relevant external-control evidence.

For a premature-termination defect, amend the authoritative scheduler/orchestrator prompt/configuration, then resume the missed or next safe GitHub lane in the same invocation when possible. Prompt repair alone is not completion evidence.

## 6. Protect queue health

Defer the exact pending identity after one read. Preserve the sole current-head evidence lane and cancel only runs proven obsolete by current PR/head/workflow identity. Interactive dispatch and scheduled sweeps use isolated concurrency so a sweep cannot replace interactive work.

After every substantive action or defer decision, reselect the queue. Before termination perform the double exit sweep; if either sweep finds an execute-now item, execute it and continue.

## 7. Reconcile durable decisions

If the incident changes automation behavior, evidence authority, writer leases, security, operations, or acceptance semantics, reconcile the durable decision into the existing canonical GitHub documentation line. Conversation text, prompt text, PR bodies, and incident comments remain evidence inputs. Product-specific behavior stays in the owning product repository.

## 8. Merge and operational acceptance

Merge only after actual protection and counted independent exact-head approval pass. For operational defects, exercise the protected-main scheduled/manual consumer, verify downstream acknowledgement and negative control, and rehearse rollback before closure.

A documentation or prompt change can be source-level acceptance for the control definition, but an incident about actual scheduler behavior closes only after runtime evidence demonstrates correct lane rotation/termination behavior.

## 9. Reopen conditions

Reopen when the same failure class recurs, a run again terminates while a safe lane remains, the protected-main consumer did not execute the repaired boundary, documentation authority splits again, evidence was stale/synthetic, rollback was not viable, or a security control was weakened to obtain green status.
