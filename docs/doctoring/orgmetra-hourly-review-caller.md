# Orgmetra hourly review-repair caller

## Decision

`ContextualWisdomLab/.github` owns the reusable scheduler and bounded writer
boundary. This caller targets `ContextualWisdomLab/Orgmetra`; Orgmetra owns
only this thin caller, which targets the protected develop (`develop`) branch at
minute 58 of every hour, inspects at most 50 open pull
requests, and dispatches at most one exact-head repair.

The caller preserves Orgmetra as a standalone HRIS/HCM product. It does not
copy People API, PostgreSQL, psychometrics, contextual-orchestrator, OpenCode,
or provider implementation code into the central automation repository.

## RCA and remediation feasibility

The worker refetches the live pull request, base, head, review state, failed
checks, changed paths, and writer authority before any edit. It establishes
root-cause analysis and evaluates remediation feasibility before selecting the
smallest permitted change. Queued or pending checks remain merge blockers;
latency is not evidence for a speculative patch.

The worker leaves the tree unchanged when a remedy would require protected
setting changes, missing credentials, sealed control-plane paths, an
unavailable dependency, fabricated approval, or unverifiable behavior.

## Cadence and protection

The caller uses non-cancelling single-flight concurrency and a two-hour same-head retry floor.
The heartbeat is an opportunity to inspect eligible
work, not a real-time SLA. The separate central merge scheduler, required
checks, independent non-author approval, unresolved-thread policy, and branch
protection remain authoritative.

No caller or worker may self-approve, merge, lower branch protection, turn a
queued check green, or treat a stale-head or synthetic-merge result as current
evidence.

## Model and credential boundary

The caller maps only `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` and
never uses `secrets: inherit`, `COPILOT_GITHUB_TOKEN`, or
`NVIDIA_NIM_API_KEY`. Model execution stays in the central OpenCode worker.
The target architecture routes model-provider credentials through
contextual-orchestrator's KV registry and automatic model discovery; this
caller does not receive provider keys. Provider activation and gateway health
must be evidenced by the central worker, not inferred from this schedule.

## Orgmetra product boundary

Repairs must preserve Orgmetra's evidence-centered employment lifecycle:
person, employment, organization, job, position, and assignment remain
separate concepts; HR facts remain normalized and bitemporal where required;
purpose-bound authorization, field-level access, encryption, retention, audit,
and export controls remain intact; and LLM output never becomes an autonomous
high-impact employment decision.

The caller cannot write an Orgmetra database, read another service's
application database, store raw credentials in person records, publish a
release, or replace browser, PostgreSQL, Rust, GPU, SAST, Security Scan, or
independent review evidence with a static claim.

## Verification and rollback

The focused central quality workflow checks the exact minute, target
repository, protected base, one-dispatch budget, retry floor, read-only caller
scope, explicit credentials, and provider-key exclusions. A changed head must
be re-reviewed and re-checked before integration. Rollback is a reviewed
source change; disabling exact-head binding or approval requirements is not a
rollback.

## APA 7th references

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. Retrieved
August 20, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

GitHub. (n.d.). *Reuse workflows*. Retrieved August 20, 2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reusing-workflows

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

OpenCode. (n.d.). *OpenCode documentation*. Retrieved August 20, 2026, from
https://opencode.ai/docs/
