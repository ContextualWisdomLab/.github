# Hourly PR review-repair scheduler

The central automation separates **product cadence** from the **reusable repair
engine**.

- `clearfolio-hourly-review-repair.yml` owns Clearfolio's heartbeat at minute 23
  of every hour.
- `pr-review-fix-scheduler.yml` is the reusable, product-neutral scheduler
  module. It has no product-specific timer and can be called by naruon,
  contextual-orchestrator, or another CWL service with an explicit repository
  and base branch.
- `pr-review-autofix.yml` is the bounded write-capable worker. It uses OpenCode
  with NVIDIA NIM and does not approve or merge pull requests.

Merge eligibility remains owned by the separate merge scheduler, branch
protection, required checks, independent review, and unresolved-thread policy.

## Clearfolio execution contract

The default Clearfolio caller provides the following immutable operating
parameters to the reusable scheduler:

```yaml
target_repository: ContextualWisdomLab/clearfolio
base_branch: main
max_prs: "50"
max_dispatches: "1"
retry_hours: "1"
```

The scheduled heartbeat is `23 * * * *`. Repository-scoped concurrency and
`cancel-in-progress: true` ensure that a superseded Clearfolio queue scan does
not overlap its successor. At most one repair dispatch is created per run.

The caller passes only the established `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN` scheduler credentials. It does not receive or forward
`NVIDIA_NIM_API_KEY`; the model credential is scoped exclusively to the two
OpenCode execution steps in the separately reviewed autofix worker.

## Reusable target-selection contract

The shared scheduler resolves its target in this order:

1. `repository_dispatch` payload `target_repository`;
2. reusable-workflow input `target_repository`;
3. repository variable `PR_REVIEW_FIX_TARGET_REPOSITORY`;
4. the repository in which the scheduler executes.

This ordering keeps standalone operation possible while preventing the central
module from silently hard-coding one product. Clearfolio's product-specific
choice is visible in its dedicated caller. A sibling service can add its own
small caller or invoke the reusable workflow directly without copying the
scheduler implementation, OpenCode configuration, or model credentials.

`canonical_ref` remains an accepted deprecated input only so callers pinned to
older workflow interfaces can upgrade without a coordinated breaking change.
It is never read and cannot choose executable scheduler code.

## Immutable reusable-workflow source

GitHub associates the ordinary `github` context in a reusable workflow with the
caller. Consequently, a privileged called workflow must not use caller-derived
`github.sha`, a caller payload, or a mutable branch such as `main` to select its
co-located implementation.

The checkout step instead uses:

```yaml
repository: ${{ job.workflow_repository }}
ref: ${{ job.workflow_sha }}
```

`job.workflow_repository` identifies the repository that contains the called
workflow and `job.workflow_sha` identifies its immutable resolved commit. The
workflow validates repository, SHA, workflow ref, and file path before checkout,
then verifies the resulting Git revision before executing the scheduler helper.
Checkout credentials are not persisted.

## Security and MSA boundary

The scheduler may inspect review state and dispatch the already-reviewed bounded
autofix workflow. It cannot approve its own changes, lower branch protection,
convert queued checks to success, publish releases, or bypass independent
review. Product repositories remain independently operable and consume the
central policy as a reusable module rather than copying privileged automation.

Clearfolio, naruon, contextual-orchestrator, and other CWL services retain their
own product tests, authorization, release, deployment, data-governance, and
runtime responsibilities. The central workflow owns only organization-level
queue inspection and bounded repair dispatch.

## Verification

Permanent static tests prove:

- the Clearfolio caller owns exactly one hourly schedule and names the exact
  Clearfolio repository and protected base branch;
- the shared scheduler contains no product-specific timer or repository name;
- the default dispatch budget and same-head retry floor remain one;
- caller and reusable-workflow secret declarations are explicit and do not use
  `secrets: inherit`;
- the active product caller is included in the focused workflow path filters;
- immutable source, NVIDIA-only model authentication, child-process credential
  stripping, file allowlists, and live-head guards remain intact.

Every exact PR head must also pass all central security, coverage,
workflow-contract, automated-review, independent-review, unresolved-thread, and
branch-protection gates before merge.

## References (APA 7th edition)

GitHub, Inc. (n.d.-a). *Contexts reference: Job context*. GitHub Docs. Retrieved
August 5, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/contexts#job-context

GitHub, Inc. (n.d.-b). *Events that trigger workflows*. GitHub Docs. Retrieved
August 5, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-c). *Reusing workflows*. GitHub Docs. Retrieved August 5,
2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/how-tos/reuse-automations/reuse-workflows
