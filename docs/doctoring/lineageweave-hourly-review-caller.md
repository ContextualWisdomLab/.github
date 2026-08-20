# LineageWeave hourly review-repair caller

검토 기준일: **2026-08-20**

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/LineageWeave`. The caller covers the current buyer-surface
stack **#258 → #260 → #261 → #262 → #263 → #264**, delegates to the
product-neutral central review-fix scheduler, inspects at most 50 open pull
requests targeting protected `main`, and dispatches at most one bounded repair
per heartbeat.

The caller runs at minute 4 of every hour and also exposes `workflow_dispatch`
for an operator-controlled acceptance run. It does not contain product mutation
logic, LLM credentials, approval authority, merge authority, or release
authority. LineageWeave remains independently deployable; privileged automation
remains in `ContextualWisdomLab/.github`.

## Buyer-visible incident

A trusted `@opencode-agent` request on LineageWeave #258 did not produce a
visible receipt or a formal current-head OpenCode review. The durable repository
dispatch had already succeeded. The router then attempted a cosmetic `eyes`
reaction before publishing the acknowledgement. A target-repository HTTP 403
therefore terminated the source run before the receipt was written. The exact
invocation ledger correctly prevented duplicate dispatch, but the former early
return also prevented a later sweep from healing the missing receipt.

The scheduled sweep had a separate availability weakness: its `gh api`
subprocesses had no finite timeout, so generator shutdown could wait indefinitely
for an already-running repository request. The central repair now bounds every
request, preserves deterministic four-worker fanout, and allows a later sweep to
repair only the missing receipt without redispatch.

## Root-cause analysis and remediation feasibility

The reusable worker performs exact-head root-cause analysis and tests
remediation feasibility before it edits. It must:

1. Refetch the live head, declared base, stack dependency, formal reviews,
   unresolved threads, checks, changed paths, and active writer state.
2. Establish the first causal boundary rather than repeat a terminal symptom.
3. Enumerate materially distinct minimal remedies.
4. Reject remedies that lack writer authority, cross sealed paths, require
   unavailable credentials or protected-setting changes, violate stack order,
   cannot be verified, or do not alter the diagnosed cause.
5. Dispatch at most one feasible repair; otherwise leave the branch unchanged.

A queued or pending check remains a merge blocker but is not itself a code
finding. An independent non-author approval remains an external authorization
gate and is never synthesized by the repair worker. The worker cannot approve,
merge, release, weaken protection, dismiss valid findings by inference, or
manufacture passing evidence.

## Stack order

The active buyer surface is a dependency chain, not six unrelated pull
requests:

```text
#258
  → #260
    → #261
      → #262
        → #263
          → #264
```

A child is reviewed against its exact declared parent head. When a parent moves,
the child is stale until its base is updated and all exact-head checks and
reviews are regenerated. A green result from an ancestor, predecessor head, or
sibling cannot satisfy a descendant gate.

## Cadence and concurrency

The caller uses one repository-scoped concurrency group and
`cancel-in-progress: false`. A later heartbeat must not discard an in-flight
lineage, ontology, temporal-event, or buyer-surface root-cause analysis.

GitHub Actions **`queue: max` is valid** concurrency syntax as of May 7, 2026.
It preserves up to 100 pending runs when `cancel-in-progress` is false or
omitted. The central mention router therefore retains `queue: max`; the
LineageWeave heartbeat itself remains non-cancelling and bounded to one repair.

The caller sets a **two-hour same-head retry floor**. OpenCode and NVIDIA NIM
review, plus a full stacked-PR evidence pass, can legitimately exceed one hour.
Redispatching an unchanged head every hour would create duplicate writers rather
than faster remediation.

GitHub scheduled workflows execute from the default branch and can be delayed
under Actions load. The cron expression is a heartbeat, not a real-time SLA.
`workflow_dispatch` permits a deliberate post-merge acceptance run without
changing the cadence or credential boundary.

## Credential and model boundary

The caller keeps workflow `GITHUB_TOKEN` at `contents: read`. Only the reusable
job receives `id-token: write`, allowing the reviewed central scheduler to use
its established GitHub OIDC credential path when required. The caller maps only
`PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN`; it never uses
`secrets: inherit`, receives `NVIDIA_NIM_API_KEY`, or introduces
`COPILOT_GITHUB_TOKEN`.

Model execution remains inside the separately reviewed central worker. Before
protected-main activation, `OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain
the exact `ContextualWisdomLab/LineageWeave` repository. A missing or mismatched
target fails before a mutation credential is materialized.

## Operational acceptance

Source checks are necessary but do not constitute **protected-main operational
acceptance**. Closure requires all of the following after the central repair and
this caller reach protected `main`:

1. Post one fresh trusted `@opencode-agent` request against the then-current
   exact head of LineageWeave #258.
2. Observe the central sibling-repository sweep discover that source comment.
3. Observe a durable exact-name invocation claim and a visible receipt containing
   the source-comment marker and exact head.
4. Prove that a reaction failure cannot suppress the receipt.
5. Prove that the next sweep does not redispatch the same exact request.
6. Observe the downstream OpenCode workflow publish a formal exact-head review
   or explicit fail-visible evidence.
7. Run the LineageWeave hourly caller and verify that it selects no more than one
   eligible exact-head repair.
8. Re-evaluate #260 through #264 in dependency order after every parent-head
   movement.

Merge still requires zero unresolved valid findings, all required exact-head
checks, and qualifying independent approval. Static workflow syntax, a dispatch
receipt, or a green status alone is not a review verdict.

## Verification and rollback

Machine-checkable contracts require:

- exact `ContextualWisdomLab/LineageWeave` target and protected `main` base;
- minute 4 hourly cadence plus a manual acceptance entry point;
- non-cancelling repository-scoped concurrency;
- at most one dispatch and a two-hour same-head retry floor;
- read-only workflow contents plus job-scoped OIDC;
- explicit scheduler-secret mapping;
- absence of model, Copilot, merge, release, and target-mutation authority;
- a focused path-filtered quality workflow for caller, test, and doctoring; and
- no product identity hard-coded in the reusable scheduler.

Rollback removes only this caller, its focused quality workflow, its contract
test, and its doctoring records. It must not remove the product-neutral
scheduler, the central mention-router repair, or another product caller.

## APA 7th references

GitHub, Inc. (2026, May 7). *GitHub Actions concurrency groups now allow larger
queues*. GitHub Changelog.
https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 20, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August 20,
2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *OpenID Connect reference*. GitHub Docs. Retrieved
August 20, 2026, from
https://docs.github.com/en/actions/reference/security/oidc

MITRE. (2026). *CWE-250: Execution with unnecessary privileges*.
https://cwe.mitre.org/data/definitions/250.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

NVIDIA. (n.d.). *NVIDIA NIM for large language models documentation*. Retrieved
August 20, 2026, from
https://docs.nvidia.com/nim/large-language-models/latest/

OpenCode. (n.d.). *OpenCode documentation*. Retrieved August 20, 2026, from
https://opencode.ai/docs/
