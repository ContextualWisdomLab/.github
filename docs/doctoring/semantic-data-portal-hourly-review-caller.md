# Semantic Data Portal hourly review-repair caller

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/semantic-data-portal`. The caller runs at minute 31,
delegates to the product-neutral central review-fix scheduler, inspects at most
50 open pull requests, and dispatches at most one bounded repair per heartbeat.
The minute avoids every other caller's cron slot (2, 10, 14, 16, 21, 23, 27,
37, 43, 49, 53, 58) and the minute-zero runner surge.

The caller does not implement review or mutation logic itself. It keeps the
portal independently operable while centralizing privileged automation in
`ContextualWisdomLab/.github`. The reusable worker performs exact-head
root-cause analysis, tests remediation feasibility, and edits only when one
small reversible action can change the diagnosed cause inside its sealed
writer authority.

## Root-cause analysis and remediation feasibility

The portal queue is dependency-ordered: the shared-base cryptography unlock
merges before the security lock, Keyverse claim aliases, the SQL gate pair,
and then the catalog-plane stack. An hourly redispatch of an unchanged head
does not accelerate that order; it duplicates writer pressure. The worker
therefore enforces these transitions:

1. Refetch the exact live head, base, reviews, checks, changed paths, and
   writer state.
2. Establish the causal chain rather than repeat the terminal symptom.
3. Enumerate materially distinct minimal remedies.
4. Reject remedies that lack writer authority, cross sealed paths, require
   unavailable credentials or protected-setting changes, violate stack order,
   cannot be verified, or do not alter the diagnosed cause.
5. Dispatch at most one feasible repair. Otherwise leave the tree unchanged so
   another eligible pull request can be considered by a later heartbeat.

A queued or pending check remains a merge blocker but is not itself a code
finding. The independent non-author approval remains an external authorization
gate and is never synthesized by the repair worker. Product-gap development
that a heartbeat cannot safely automate (for example the Data Management
Evidence Console) stays with the repository's own issue-driven loop; the caller
never fabricates UI evidence to fill it.

## Cadence and concurrency

The caller uses a single concurrency group and `cancel-in-progress: false`.
This preserves an in-flight bounded RCA instead of discarding its evidence when
the next hourly heartbeat arrives. The reusable scheduler cancels only its own
superseded short queue scan; the separately dispatched per-PR repair worker and
this product caller remain non-cancelling. The central scheduler and per-PR
worker also retain exact-head leases and mutation limits.

The caller sets a **two-hour same-head retry floor**. Central OpenCode and
NVIDIA NIM work can legitimately approach two hours, so an hourly redispatch of
the same unchanged head would create duplicate writer pressure rather than
faster remediation. A later hourly scan can still select another eligible pull
request.

GitHub scheduled workflows can be delayed under load and execute only from the
default branch. Consequently, the cron expression is a heartbeat rather than a
real-time service-level promise. Exact-head state, not elapsed wall-clock time,
controls every mutation and merge decision.

## Credential and model boundary

The queue-scanning caller has only `contents: read`. It maps only the
established `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` scheduler
credentials and does not use `secrets: inherit`.

Model execution remains inside the central worker. The model credential is the
GitHub Secret `NVIDIA_NIM_API_KEY`; the caller does not receive or forward it.
`COPILOT_GITHUB_TOKEN` is prohibited. GitHub tokens and GitHub Models are not
model credentials for this write-capable path. The independent review-agent
credential contract is unchanged.

## Security, standalone operation, and modularity

The caller adds no portal runtime dependency, database object, network
endpoint, tenant authority, or product credential. The semantic-data-portal
continues to run as a standalone FastAPI application and as a module beside
naruon, Keyverse, DiskSage, fast-mlsirm, TEPP, LineageWeave, RankWeave, and
contextual-orchestrator without weakening its local validation,
protected-branch, exact-head, approval, or security gates. Authority boundaries
stay fixed: identity belongs to Keyverse, policy truth to GRC, capability
targets to enterprise-architecture-core, document-KG writes to naruon, lineage
reconstruction to LineageWeave, and central governance to this repository.

The reusable workflow source is bound to the called workflow repository, SHA,
ref, and file path before privileged scheduler logic runs. The worker cannot
approve, merge, release, weaken checks, change reviewer identities, or modify
protected settings. Queued, pending, absent, failed, cancelled, skipped-required,
neutral-required, stale-head, or synthetic-merge evidence is not success.

## Verification and rollback

Repository contracts require the exact cron, target repository, one-dispatch
budget, two-hour retry floor, non-cancelling single-flight policy, read-only
workflow token, explicit secret mapping, and absence of both
`NVIDIA_NIM_API_KEY` and `COPILOT_GITHUB_TOKEN` from the caller.

Rollback is a reviewed source change. Do not disable exact-head binding, reduce
the independent approval requirement, increase dispatch volume, use inherited
secrets, or convert provider latency into a fabricated code edit. If the
heartbeat becomes too frequent or too slow, change only the caller cadence and
retry floor after examining observed run duration and queue throughput; preserve
the central RCA, feasibility, lease, and credential contracts.

## APA 7th references

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. Retrieved
August 25, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

GitHub. (n.d.). *Events that trigger workflows: Schedule*. Retrieved August 25,
2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub. (n.d.). *Reuse workflows*. Retrieved August 25, 2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reusing-workflows

NVIDIA. (n.d.). *NVIDIA NIM for large language models documentation*. Retrieved
August 25, 2026, from
https://docs.nvidia.com/nim/large-language-models/latest/

OpenCode. (n.d.). *OpenCode documentation*. Retrieved August 25, 2026, from
https://opencode.ai/docs/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
