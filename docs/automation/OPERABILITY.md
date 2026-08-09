# Automation control-plane operability

Status: active_pr

## Service objectives

- Every mutation is bound to a freshly observed exact head/blob/ref.
- No required evidence is promoted from stale, pending, cancelled, skipped, absent, or predecessor state.
- A blocked lane does not prevent execution of another safe lane.
- A prompt update, documentation update, RCA, review request, merge, or user-visible status does not terminate a run while another safe executable lane exists.
- Every substantive action or defer decision produces queue reselection and a `continuation_handoff` unless the practical invocation/tool budget is exhausted.
- Termination is preceded by the required fresh double exit sweep.
- Current-head required checks queued beyond the declared repository SLO are diagnosable by repository, workflow, run, event, head, queue age, and external prerequisite.
- Operational incidents close only after a current protected-main consumer and negative control pass.

## Signals

Track queue age, executable-lane count, deferred-lane count and exact defer identity, last substantive action, next selected lane, continuation-handoff count, exit-sweep result, premature-termination detection, running/pending lanes per PR and workflow, obsolete-run count, provider failure class, retry count, dispatch acknowledgement, reviewer eligibility, unresolved thread count, exact-head check completeness, external scheduler/automation writer-lease state, secret materialization, redaction events, merge result, canonical documentation fitness, and protected-main acceptance identity.

## Premature-termination incident

Classify a run as prematurely terminated when its terminal/user-visible output is followed by fresh evidence that a safe, policy-compliant lane was executable under the current writer lease. Treat the emitted status as the symptom; the root cause is the prompt/control condition that promoted an intermediate state to terminal.

Remediation is work-conserving: repair the authoritative scheduler prompt/configuration, refetch the missed queue, execute the highest-value safe lane in the same invocation when possible, and update the canonical documentation/test contract when a durable invariant was missing. Prompt repair by itself is not incident closure.

## Degraded operation

- Provider outage/rate limit: defer model evidence; continue deterministic and disjoint work.
- Runner saturation: preserve the sole current-head required run; cancel only proven obsolete runs.
- DNS/network bootstrap failure: retry only bounded transient classes with backoff; integrity, auth, TLS, ref, and origin failures fail immediately.
- External human approval: enable expected-head-safe auto-merge when appropriate and continue other work.
- OIDC/App failure: keep credentials undisclosed, record the failed envelope boundary, and fall back only to a separately authorized path.
- Documentation authority conflict: freeze only the conflicting documentation lane, resolve canonical ownership from live repository state, retain superseded history, and continue disjoint work.
- External scheduler/control read failure: fail closed on writer-lease mutation for the affected repository but continue read-only audit or separately owned lanes.

## Replay and rollback

Rerun only the failed exact-head job when evidence remains valid and the workflow contract supports it. Never use rerun churn to mask a source defect. Roll back the smallest protected-main change, disable the narrow caller, and retain incident evidence for reacceptance.

For continuation-policy regressions, roll back only the external prompt/configuration delta when it causes unsafe selection; writer leases and GitHub gates remain intact. Re-enable the repaired continuation policy only after a deterministic queue scenario proves a blocked lane rotates to another safe lane and the exit-sweep contract behaves as specified.
