# ADR-0007: Maintenance is work-conserving; reporting is not completion

Status: Accepted
Date: 2026-08-09
Decision owners: CWL product and automation maintainers

## Context

Long model reviews, human approval, queued checks, provider cooldowns, and one blocked PR repeatedly caused finite maintenance invocations to stop after reporting status. An hourly recurrence then became an excuse to defer work despite safe tasks in other branches, docs, issues, operations, or product gaps. A second failure mode appeared when prompt edits, documentation audits, review requests, CI dispatches, Draft/Ready transitions, auto-merge enablement, or one successful commit/merge were treated as convenient endpoints even though safe work remained.

Repeated user redirection exposed a third control failure: after being told explicitly that executable work remained, the automation could repair its prompt or documentation and still terminate without proving that repository execution had actually resumed. A scheduler that treats the redirection itself as another reporting opportunity has not corrected the failed exit condition. The recovery therefore needs an observable same-invocation execution requirement rather than another prose-only reminder.

Historical scheduler guidance also encoded a fixed 45-minute execution budget and a minute-35 prohibition on beginning new repository writes. That policy was useful as an early collision-avoidance heuristic but is now superseded because it turned elapsed wall-clock time into an implicit completion signal even when another bounded, non-conflicting action was executable. A fixed wall-clock cutoff therefore cannot authorize a clean exit from the current maintenance architecture.

## Decision drivers

- Maximize validated repository progress within each finite invocation.
- Avoid polling and repetitive blocker narration.
- Keep dependencies and writer safety without serializing the whole fleet.
- Make documentation and operational proof first-class work without allowing them to substitute for implementation work.
- Prevent elapsed wall-clock time or meta/control-plane activity from becoming an implicit voluntary timeout.
- Make recovery from a user-reported premature stop falsifiable in the same invocation.

## Alternatives considered

1. **Stop after one named request or blocker.** Rejected because it strands executable work.
2. **Poll until the active PR completes.** Rejected because it wastes budget and can starve the queue.
3. **Treat the hourly cadence or a fixed wall-clock cutoff as a soft budget and resume later.** Rejected because recurrence is a continuation mechanism, not evidence that the current finite invocation is work-complete.
4. **On user redirection, update the scheduler prompt and wait for the next hourly run.** Rejected because a prompt mutation is control-plane preparation, not evidence that missed repository work resumed.
5. **Maintain multiple ordered lanes, defer blocked identities, rotate after every action, require same-invocation recovery after redirection, and require a double exit sweep.** Selected.

## Decision

Each run maintains live lanes for mergeable PRs, defects/reviews/checks, protected-main acceptance, issues, documentation/automation drift, and one bounded buyer-visible gap. Pending external states enter a deferred set keyed by repository, PR, head, and run/review identity. After every substantive action the automation refreshes affected state and immediately selects another safe item.

The hourly recurrence is **continuation after genuine practical execution/tool-budget exhaustion**, never a voluntary soft timeout. A prompt update, documentation assessment/update, inventory, RCA without remediation, status or blocker comment, review request, workflow dispatch/rerun, queued/running CI or model review, Draft/Ready transition, auto-merge enablement, commit, merge, completed document, protected-main proof of one scenario, external-governance wait, or completion of one buyer-visible slice is an intermediate event with zero terminal credit while another safe lane exists.

A user statement that work was left behind creates reason code `USER_REDIRECTION_INCIDENT`. Recovery occurs in the **same invocation**. Prompt editing, inventory, RCA prose, documentation assessment/mutation, one commit/PR/check/review request/merge/blocker, or one product slice receives **zero completion credit** by itself. The automation must rebuild the full live queue and resume repository execution. If at least two independent safe execute-now lanes exist, it must perform **at least two materially distinct** substantive repository actions before termination is eligible, with at least one **non-documentation** action whenever any safe non-documentation lane exists. A documentation action can satisfy at most one of those lanes. If fresh evidence proves only one execute-now lane exists, execute it and then require **two fresh whole-queue sweeps** to prove no second lane has become executable. A final response that knowingly leaves an execute-now lane is a recurrence of the scheduler defect.

The superseded fixed 45-minute execution budget and minute-35 write cutoff are not current exit criteria. Component jobs and external model calls may still have bounded technical timeouts for safety, cost, or failure isolation, but orchestration must use remaining practical tool/runtime capacity rather than voluntarily stopping at a predeclared minute. When the platform or tool boundary actually prevents another safe action, record the continuation state and resume on the next recurrence.

Before termination, perform a **fresh whole-queue sweep** that includes PRs, issues, protected-main acceptance, docs versus implementation, quality/security/release debt, active writers, and buyer/control-plane gaps. If it finds work, execute the highest-value safe item and sweep again. Only actual practical execution/tool-budget exhaustion or a **second fresh sweep** proving every lane non-actionable permits termination. A user-redirection recovery resets the sweep count after its required substantive actions.

## Consequences

Positive: higher throughput, less queue starvation, fewer report-only runs, explicit recovery from premature-stop incidents, and durable progress while providers or humans wait. Negative: the automation needs careful scope/lease management, exact defer identities, an executable-queue view, and a continuation ledger capable of distinguishing locally blocked work from globally empty work. A redirection can require more than one branch or work family to be advanced in one finite invocation, so branch isolation and exact-head refetches remain mandatory.

## Failure and recovery

If queue selection creates conflicts or unsafe scope expansion, stop only the affected lane, record the boundary, and choose a disjoint item. If a tool/run budget is genuinely exhausted mid-item, leave exact continuation evidence and resume on the next recurrence; do not claim product completion. If a meta action accidentally becomes the last action, the next run treats that as unfinished continuation rather than completed work.

If a user points out that executable work was left behind, classify `USER_REDIRECTION_INCIDENT`, identify the last voluntary terminal condition and at least one missed lane, correct the scheduling/control contract when needed, rebuild the whole queue, and resume execution in the same invocation. When two independent execute-now lanes exist, advancing only one is still an incomplete recovery. Documentation or prompt repair cannot be the final action when non-documentation work is executable. After recovery actions, restart the two-sweep exit proof from fresh evidence.

## Security and governance impact

Work conservation never permits bypassing approval, checks, writer leases, permissions, privacy controls, or fail-closed evidence boundaries. It changes scheduling, not authority. Routine output is suppressed so status narration cannot substitute for work. The no-soft-timeout rule does not authorize unbounded single-job execution; component/job timeouts remain bounded according to their own technical contracts. The two-lane redirection rule applies only to actions independently safe under current authority and lease; it never authorizes racing another writer or weakening a merge gate merely to satisfy an action count.

## Tests and acceptance

- queued/pending item does not block selection of another lane;
- duplicate dispatch is deferred, not polled;
- branch-local lease blocks only one branch;
- docs drift appears as executable debt;
- prompt/document/status/review/dispatch/Draft/Ready/auto-merge actions cannot satisfy the run exit condition by themselves;
- one successful commit or merge cannot satisfy the exit condition while another safe lane exists;
- `USER_REDIRECTION_INCIDENT` requires same-invocation queue rebuild and substantive execution;
- user-redirection prompt/docs repair has zero completion credit by itself;
- when at least two independent safe lanes exist after redirection, at least two materially distinct substantive actions occur and one is non-documentation when available;
- a one-lane redirection recovery is followed by two fresh whole-queue sweeps proving no second execute-now lane exists;
- historical fixed wall-clock cutoffs are explicitly superseded and cannot replace practical execution/tool-budget exhaustion;
- elapsed time below a real platform/tool-budget boundary cannot substitute for an exit sweep;
- the first exit sweep finding work forces another action;
- only practical budget exhaustion or the second fresh all-lanes-non-actionable sweep permits termination; and
- scheduled-run output is empty except defined notification events.

## Migration and rollback

Update maintainer prompts and scheduler policies with the continuation ledger, `USER_REDIRECTION_INCIDENT`, same-invocation recovery, multi-lane proof, and double exit sweeps. Remove duplicative inactive loops and prompt wording that encourages status-first termination or fixed-minute voluntary exits. Rollback may reduce concurrency but must preserve no-report-as-completion, no-soft-timeout semantics, same-invocation redirection recovery, branch rotation, and the second-sweep termination proof.

## Supersession conditions

Supersede if a durable queue engine provides provably fair, dependency-aware, lease-safe work conservation and equivalent termination proofs across repositories, including explicit handling of user redirection, meta actions, external waits, and practical run-budget exhaustion.