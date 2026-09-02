# Actions queue cancellation before runner assignment

## Status

Proposed owner-side diagnostic extension for `ContextualWisdomLab/.github#1150` and the organization Actions incident tracked by `ContextualWisdomLab/.github#712`.

## Problem

A current pull-request head can produce a terminal GitHub Actions run whose job was cancelled before any runner was assigned or any step executed. Treating that evidence as a generic terminal job loses the first non-executed boundary and can mislead incident triage even though it must never count as passing evidence.

Observed organization evidence on 2026-09-02 includes `.github#1653`, where a current-head `Repository Metadata Reconcile` job terminated `cancelled` after previously showing `runner_id=0`, empty runner identity, and `steps=[]`. Separate ContextualWisdomLab repositories also reproduce zero-job `startup_failure` and long-lived unassigned queue states, so these states must remain distinct rather than being collapsed into a product-source failure.

## Decision

The queue-health collector keeps external GitHub conclusion values unchanged at the adapter boundary and adds a semantic internal/report classification. For exact current heads it now:

- retains both `startup_failure` and `cancelled` terminal diagnostics from the bounded exact-`head_sha` completed-run query;
- fetches job evidence for those retained terminal diagnostics;
- classifies a cancelled job with no runner assignment and zero executed/materialized steps as `cancelled_before_runner_assignment`;
- keeps zero-job startup failures as `startup_failure_before_job_materialization`;
- reports an additive `admission_state` and a summary count without changing any GitHub check conclusion or synthesizing success;
- recommends inspection of Actions runner admission, billing/usage, runner-group policy, scheduler capacity, concurrency, and cancellation provenance rather than leaf-source churn or gate weakening.

## TDD lineage

RED commit `af72a26e0d1d845a7b447a63c7d4de4867815a87` adds a deterministic regression whose current-head cancelled run has one job with `runner_id=0`, an empty runner name, and `steps=[]`. The predecessor production contract retained only `startup_failure` terminal diagnostics and therefore could not satisfy the regression.

GREEN commit `79e0758d0583474934327039b065956976c64453` extends the canonical collector and report classification while preserving exact-head identity, bounded pagination, read-only operation, and fail-closed merge semantics.

## Compatibility and risk

This is an additive diagnostic-contract change. It does not mutate repository branches outside the canonical PR, cancel/rerun Actions, alter branch protection, change database state, or modify an external GitHub schema. `status`, `conclusion`, `runner_id`, and related GitHub payload keys remain vendor-owned adapter fields; organization-owned report vocabulary uses semantic multiword names.

The collector remains bounded to the existing exact-current-head completed-run search ceiling. A cancelled job that had a runner assignment or executed steps remains ordinary terminal evidence and is not reclassified as a pre-runner admission failure.

## Verification

Only checks produced from the unchanged final `ContextualWisdomLab/.github#1150` head qualify. Queued, pending, cancelled, zero-job startup failures, predecessor checks, or stale reviews are incomplete evidence and must not be transferred to a newer head.