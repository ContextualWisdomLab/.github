# Actions queue cancellation before runner assignment

## Status

Proposed owner-side diagnostic extension for `ContextualWisdomLab/.github#1150` and the organization Actions incident tracked by `ContextualWisdomLab/.github#712`.

## Problem

A current pull-request head can produce a terminal GitHub Actions run whose job was cancelled before any runner was assigned or any step executed. Treating that evidence as a generic terminal job loses the first non-executed boundary and can mislead incident triage even though it must never count as passing evidence.

Observed organization evidence on 2026-09-02 includes `.github#1653`, where a current-head `Repository Metadata Reconcile` job terminated `cancelled` after previously showing `runner_id=0`, empty runner identity, and `steps=[]`. Separate ContextualWisdomLab repositories also reproduce zero-job `startup_failure` and long-lived unassigned queue states, so these states must remain distinct rather than being collapsed into a product-source failure.

A second adapter-boundary case is `pull_request_target`: GitHub records the workflow run against the base commit while the linked pull-request object carries the exact pull-request head. A terminal diagnostic collector that searches only by the current pull-request `head_sha` therefore cannot see a target-triggered cancellation even when its linked pull-request identity is current.

## Decision

The queue-health collector keeps external GitHub conclusion values unchanged at the adapter boundary and adds a semantic internal/report classification. For exact current heads it now:

- retains `startup_failure` and `cancelled` terminal diagnostics from the bounded exact-`head_sha` completed-run query for ordinary pull-request/head-bound runs;
- performs bounded `pull_request_target` terminal-status candidate reads and retains a candidate only after the existing linked pull-request number/head identity resolver proves it belongs to an exact current head;
- fetches job evidence only for retained current-head terminal diagnostics;
- classifies a job as `cancelled_before_runner_assignment` only when both the run and that job conclude `cancelled`, the job has no runner assignment, and it has zero executed/materialized steps;
- never reclassifies sibling jobs that concluded `skipped`, `success`, or another non-cancelled state merely because their parent run concluded `cancelled`;
- keeps zero-job startup failures as `startup_failure_before_job_materialization`;
- reports an additive `admission_state` and a summary count without changing any GitHub check conclusion or synthesizing success;
- recommends inspection of Actions runner admission, billing/usage, runner-group policy, scheduler capacity, concurrency, and cancellation provenance rather than leaf-source churn or gate weakening.

## TDD lineage

RED commit `af72a26e0d1d845a7b447a63c7d4de4867815a87` added the first deterministic regression whose current-head cancelled run has one job with `runner_id=0`, an empty runner name, and `steps=[]`. GREEN commit `79e0758d0583474934327039b065956976c64453` introduced the initial cancellation classification.

RED commit `b4f95bc290e625649b8ce7ae59e157c3869466f2` then captured two successor defects found on the live writer: a `pull_request_target` cancellation whose run-level SHA is the base commit but whose linked pull-request head is current, and a skipped sibling job inside a cancelled run that must not be counted as a pre-runner cancellation incident. GREEN commit `5a4950bb996f80f7be2519432a3f5b74bea02d58` adds bounded target-event candidate collection with linked-head verification and requires the matched job itself to conclude `CANCELLED` before applying the semantic incident classification.

## Compatibility and risk

This is an additive diagnostic-contract change. It does not mutate repository branches outside the canonical PR, cancel/rerun Actions, alter branch protection, change database state, or modify an external GitHub schema. `status`, `conclusion`, `runner_id`, and related GitHub payload keys remain vendor-owned adapter fields; organization-owned report vocabulary uses semantic multiword names.

Exact-head completed-run searches retain the existing twenty-page / 1,000-result fail-closed ceiling. Because GitHub's repository workflow-run API does not expose a pull-request-number filter for `pull_request_target`, target-event terminal candidates are read by terminal status and event under the same bounded ceiling, then filtered by linked current-head identity before retention. If that bounded candidate set is exceeded, the repository becomes explicit incomplete collection evidence rather than silently truncating or weakening exact-head identity. This is an availability trade-off, not permission to synthesize success or churn leaf repositories.

A cancelled run with a runner-assigned, step-executing, or non-cancelled matched job remains ordinary terminal evidence and is not reclassified as a pre-runner admission failure.

## Verification

Only checks produced from the unchanged final `ContextualWisdomLab/.github#1150` head qualify. Queued, pending, cancelled, zero-job startup failures, predecessor checks, or stale reviews are incomplete evidence and must not be transferred to a newer head. The RED/GREEN lineage above documents source intent; hosted 100% statement/branch/docstring and required-workflow evidence must be re-established on the final exact head before ordinary merge.