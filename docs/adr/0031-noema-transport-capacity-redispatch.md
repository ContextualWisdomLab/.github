# ADR-0031: Noema transport-capacity failures schedule a bounded continuation re-dispatch

- **Status:** Accepted
- **Date:** 2026-09-17
- **Scope:** `scripts/ci/noema_review_gate.py`, `.github/actions/noema-review/two_phase.py`, `.github/workflows/noema-review.yml`
- **Issue:** ContextualWisdomLab/.github#2165
- **Does not amend:** ADR-0003 (gateway owns provider failover), ADR-0005 (no model-path wall-clock timeout; superseded attempt ceilings stay historical)

## Problem

`Required Noema Review` is an organization required check. The Noema caller issues
exactly one gateway request and delegates provider discovery, repair, and failover to
contextual-orchestrator (ADR-0003). When every free-pool route is transiently
unavailable or rate-limited, the gateway returns a terminal HTTP 429 or 5xx after it has
already exhausted its own failover chain. The caller then fails closed with
`NoemaTransportError` and `caller attempts=1`. That is correct for review integrity —
the check must not be skipped — but it leaves consumer PRs permanently BLOCKED until a
human re-dispatches into a healthier window, even when the PR's own code checks are green
(#2165 evidence on four-pillars and fast-mlsirm).

Holding the same job open to retry the model call would occupy a scarce Actions runner
for provider capacity that the gateway already reported as exhausted. Product goal
directive §8 and ADR-0005 forbid converting elapsed inference time into a local
model-failure verdict or restoring fixed model-path attempt ceilings.

## Decision

1. **Classify, do not re-interpret.** HTTP 429 and 5xx from the already-failed-over
   gateway are typed as `provider_capacity_unavailable`. Malformed model output, 4xx
   other than 429, and local validation failures stay terminal review failures. The
   required check still fails; review is never skipped or auto-approved.
2. **One gateway request per job stays the contract.** `call_llm` does not gain a caller-side retry loop. Provider failover remains contextual-orchestrator's job.
3. **Continuation re-dispatch is the recovery lever.** When the failure is
   `provider_capacity_unavailable` and the run's `transport_retry_attempt` is below the
   bound (`MAX_TRANSPORT_REDISPATCH_ATTEMPTS = 2`), the workflow schedules exactly one
   same-head `repository_dispatch` (`noema-review`) with an incremented attempt counter
   after a short jitter delay. The new job is a fresh admission/continuation; the failed
   job remains failed evidence for that attempt.
4. **Jitter is post-failure scheduling, not a model timeout.** Prefer a whole-seconds
   `Retry-After` from the gateway error when present and in `[1, 300]`. Otherwise use a
   deterministic delay in `[60, 180]` seconds derived from the exact head SHA and attempt
   number so concurrent capacity failures do not stampede the free pool. That sleep runs
   only in the post-failure scheduling step and never wraps `opener.open`.
5. **Surface gateway attempt evidence.** When the error envelope carries an `attempts`
   list (orchestrator failover telemetry), the public Actions warning and exception text
   include `provider_attempt_count=<n>` alongside the existing last-attempt fields so
   capacity incidents are distinguishable from code-review verdicts without dumping raw
   provider bodies.

## Consequences

- A capacity storm produces at most three Noema jobs per head (initial + two automatic
  re-dispatches) before failing closed for operator intervention.
- Runner occupancy for a dead pool is one failed inference plus ≤180 s of scheduling
  jitter, not another multi-hour in-job wait on the same slot.
- Gateway routing bugs (for example a non-transient 400 on one ready route while others
  remain unused) are **out of scope** here; they belong to contextual-orchestrator route
  selection, not this caller (#2165 consumer notes on vision-model 400s).
- Private-target ZDR pool exhaustion (#2148) shares the classification and attempt
  evidence, but does not widen this ADR's re-dispatch bound.

## Alternatives considered

- **In-job retry of `call_llm`.** Rejected: duplicates gateway failover, burns the runner
  against an exhausted pool, and conflicts with the single-request contract tests.
- **Mark the required check neutral/success on capacity loss.** Rejected: weakens
  "review cannot be skipped."
- **Unbounded re-dispatch.** Rejected: amplifies 429 pressure (#2165 filing notes).
- **Rely only on the merge scheduler's next tick.** Deferred as a complementary path;
  it does not give the Noema workflow its own bounded, evidence-typed recovery when the
  scheduler is not looking at that head.

## 2026-09-25 authority repair

Noema run [36024200990](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/36024200990)
classified a gateway HTTP 429 and entered the bounded continuation, but the
`repository_dispatch` returned HTTP 403. The reviewer App token requested only
`Contents: read`; GitHub requires `Contents: write` for that endpoint. The
reviewer still has only `Contents: read`. A separate post-failure job now uses
the target repository's job-scoped `GITHUB_TOKEN` with `contents: write` only
to schedule the same-head continuation. That job runs no provider or PR-head
code, checks the live PR head after the bounded delay, and retains the two
continuation limit. Hosted recovery remains unverified until this workflow
lands and a real capacity failure schedules a new run.
