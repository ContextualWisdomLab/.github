# Contextual Orchestrator Hourly Review-Repair Caller Boundary

## Decision

Contextual Orchestrator owns one product-specific review → repair → exact-head
revalidation heartbeat at minute 17 of every hour. The thin caller is
`.github/workflows/contextual-orchestrator-hourly-review-repair.yml`; the
product-neutral queue and bounded repair engine remain in
`.github/workflows/pr-review-fix-scheduler.yml`.

The repository name is intentionally the current product name. The minute-17
slot previously described an unnamed “orchestrator” caller, so this workflow
also removes that internal-name drift without changing the scheduler module.

## Operating contract

The caller passes these immutable inputs:

```yaml
target_repository: ContextualWisdomLab/contextual-orchestrator
base_branch: main
max_prs: "50"
max_dispatches: "1"
retry_hours: "1"
```

The caller keeps `cancel-in-progress: false` so a long root-cause analysis is
not discarded by the next heartbeat. The reusable queue scanner still bounds
each invocation and the dispatched worker still rechecks the exact PR head
before writing.

## Credential and reviewer boundary

Only `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` cross this caller
boundary. The caller does not use `secrets: inherit`, `COPILOT_GITHUB_TOKEN`,
`NVIDIA_NIM_API_KEY`, or any provider credential. Provider credentials belong
to the separately reviewed OpenCode worker and are never exposed to queue
inspection.

The worker may use the contextual-orchestrator gateway for this target after
the gateway sidecar has passed its own pinned-source, credential-bootstrap,
model-discovery, and health checks. The existing reviewer key scheme remains
the fallback for all other target repositories; this caller does not replace
or self-approve the established review Agent.

The gateway bootstrap accepts these five provider credentials and stores them
in the KV seam before the long-lived process starts. The running process does
not use them as ambient environment fallbacks:

| Provider | Credential name |
| --- | --- |
| Bytez | `BYTEZ_API_KEY` |
| NVIDIA NIM primary | `NVIDIA_NIM_API_KEY` |
| NVIDIA NIM secondary | `NVIDIA_NIM_API_KEY_SUB` |
| OpenRouter | `OPENROUTER_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |

The bootstrap discovers the provider model catalogs, refreshes the available
price data, enables the bounded lowest-cost candidates for failover, and
requires an authenticated `/v1/models` response before OpenCode starts. A
missing key or an empty discovery result stops this target-scoped worker before
any PR file is edited.

## Failure and merge policy

Missing credentials, unavailable gateway discovery, provider errors, queued
checks, unresolved review threads, stale approvals, and head movement remain
fail-closed evidence. The scheduler records the root cause and continues with
the next independent PR or product-gap slice. It never manufactures approval,
turns a queued check green, lowers branch protection, or merges around an
independent reviewer.

## Verification

The focused central workflow must rerun when this caller or this doctoring
record changes. Its contract test checks the hourly cron, explicit repository
and base branch, bounded dispatch, non-cancelling concurrency, read-only
caller permission, explicit credential mapping, and absence of
`COPILOT_GITHUB_TOKEN` and direct model-provider secrets.

## References (APA 7th edition)

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 21, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reusing workflows*. GitHub Docs. Retrieved August 21,
2026, from
https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *Workflow syntax for GitHub Actions: Permissions*.
GitHub Docs. Retrieved August 21, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#permissions
