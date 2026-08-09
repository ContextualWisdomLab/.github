# ADR-0003 — Work-conserving execution and no report-as-completion

Status: active_pr

## Context

Autonomous maintenance previously risked ending after a single useful action or repeatedly narrating a blocker while other safe work remained. The same failure can occur after a prompt update, documentation audit, review request, merge, RCA, or user-visible status when the control plane mistakes an intermediate event for a valid invocation endpoint.

## Alternatives

1. One task per scheduled invocation.
2. Wait on the highest-priority blocked item.
3. Maintain a live executable queue and rotate around blocked lanes.

## Decision

Use option 3. A commit, review request, queued check, merge, documentation update, prompt update, RCA, defer decision, external blocker, or user-visible status is intermediate while another safe action exists. The hourly schedule is continuation after genuine finite budget exhaustion, not a one-action quota and not a substitute for same-invocation queue utilization.

After every substantive action or defer decision, refetch enough live state to choose the next executable lane. Before termination, perform a fresh queue-wide sweep. If that sweep finds executable work, act and sweep again. A valid normal termination therefore requires a second fresh sweep with no execute-now item, unless the practical invocation/tool budget is exhausted.

ADR-0010 extends this rule to conversation/prompt/documentation reconciliation and the explicit `continuation_handoff` authority boundary.

## Consequences

Invocations use more of their practical execution budget and reduce queue starvation. State management, defer identity, continuation handoff, and writer conflict handling must be stricter. External waits are intentionally local rather than invocation-global.

## Failure and recovery

Defer blocked items by exact identity and revisit only after material state change, another substantive action, or an exit sweep. If a terminal response is emitted while fresh evidence shows another safe lane was executable, classify the run as prematurely terminated, repair the authoritative continuation condition, and resume the missed or next safe lane in the same invocation when possible.

## Security and governance

Work conservation never authorizes weaker gates, unsafe parallel writers, fabricated approvals, speculative mutations, invented credentials, or cross-lease writes. Unsafe work is deferred; the queue rotates only to a separately safe lane.

## Acceptance

Automation contracts require double whole-queue exit sweeps and prohibit termination when any safe merge, fix, addressed-thread resolution, duplicate closure, Draft/issue advancement, documentation repair, operational proof, release preparation, test/security/reliability action, or bounded product/control-plane action remains. Runtime acceptance should include a scenario where one lane is blocked and another is demonstrably selected before termination.

## Supersession

Supersede only if a scheduler can prove equivalent or stronger queue utilization, same-invocation continuation, termination evidence, and safety with a different execution policy.
