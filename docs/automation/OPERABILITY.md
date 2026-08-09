# Automation control-plane operability

Status: active_pr

## Service objectives

- Every mutation is bound to a freshly observed exact head/blob/ref.
- No required evidence is promoted from stale, pending, cancelled, skipped, absent, or predecessor state.
- A blocked lane does not prevent execution of another safe lane.
- Current-head required checks queued beyond the declared repository SLO are diagnosable by repository, workflow, run, event, head, queue age, and external prerequisite.
- Operational incidents close only after a current protected-main consumer and negative control pass.

## Signals

Track queue age, running/pending lanes per PR and workflow, obsolete-run count, provider failure class, retry count, dispatch acknowledgement, reviewer eligibility, unresolved thread count, exact-head check completeness, secret materialization, redaction events, merge result, and protected-main acceptance identity.

## Degraded operation

- Provider outage/rate limit: defer model evidence; continue deterministic and disjoint work.
- Runner saturation: preserve the sole current-head required run; cancel only proven obsolete runs.
- DNS/network bootstrap failure: retry only bounded transient classes with backoff; integrity, auth, TLS, ref, and origin failures fail immediately.
- External human approval: enable expected-head-safe auto-merge when appropriate and continue other work.
- OIDC/App failure: keep credentials undisclosed, record the failed envelope boundary, and fall back only to a separately authorized path.

## Replay and rollback

Rerun only the failed exact-head job when evidence remains valid and the workflow contract supports it. Never use rerun churn to mask a source defect. Roll back the smallest protected-main change, disable the narrow caller, and retain incident evidence for reacceptance.
