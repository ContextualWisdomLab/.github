# ADR-0003 — Work-conserving execution and no report-as-completion

Status: active_pr

## Context

Autonomous maintenance previously risked ending after a single useful action or repeatedly narrating a blocker while other safe work remained.

## Alternatives

1. One task per scheduled invocation.
2. Wait on the highest-priority blocked item.
3. Maintain a live executable queue and rotate around blocked lanes.

## Decision

Use option 3. A commit, review request, queued check, merge, documentation update, RCA, or external blocker is intermediate while another safe action exists. The hourly schedule is continuation after finite budget exhaustion, not a one-action quota.

## Consequences

Invocations use more of their practical execution budget and reduce queue starvation. State management and writer conflict handling must be stricter.

## Failure and recovery

Defer blocked items by exact identity and revisit only after material state change, another substantive action, or the final sweep.

## Security and governance

Work conservation never authorizes weaker gates, unsafe parallel writers, fabricated approvals, or speculative mutations.

## Acceptance

Automation contracts require a final whole-queue sweep and prohibit termination when any safe merge, fix, documentation repair, operational proof, issue, or bounded product action remains.

## Supersession

Supersede only if a scheduler can prove equivalent queue utilization and safety with a different execution policy.
