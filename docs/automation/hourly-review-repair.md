# Hourly PR review-repair scheduler

The central `PR Review Fix Scheduler` provides a bounded organization-wide
review → fix → revalidate → merge support loop. It runs at minute 23 of every
hour and may dispatch at most one existing autofix workflow per run. Merge
eligibility remains owned by the separate merge scheduler, branch protection,
required checks, independent review, and unresolved-thread policy.

## Execution and compatibility contract

- The scheduled heartbeat is `23 * * * *`.
- The default same-head retry floor is one hour.
- `max_dispatches` remains one by default.
- Repository-scoped concurrency and `cancel-in-progress: true` prevent two
  superseded scheduler runs from mutating the same repository concurrently.
- `canonical_ref` remains an accepted deprecated input only so callers pinned to
  older workflow interfaces can upgrade without a coordinated breaking change.
  It is never read and cannot choose executable scheduler code.

## Immutable reusable-workflow source

GitHub associates the ordinary `github` context in a reusable workflow with the
caller. Consequently, a called privileged workflow must not use caller-derived
`github.sha`, a caller payload, or a mutable branch such as `main` to select its
co-located implementation.

The checkout step instead uses:

```yaml
repository: ${{ job.workflow_repository }}
ref: ${{ job.workflow_sha }}
```

`job.workflow_repository` identifies the repository that contains the called
workflow and `job.workflow_sha` identifies its immutable resolved commit. This
keeps the scheduler implementation aligned with the exact workflow revision
selected by the caller's `uses: ...@<sha>` reference. Checkout credentials are
not persisted.

## Security and MSA boundary

The scheduler can inspect review state and dispatch the already-reviewed bounded
autofix workflow. It cannot approve its own changes, lower branch protection,
convert queued checks to success, publish releases, or bypass independent
review. Product repositories remain independently operable and consume the
central policy as a reusable module rather than copying privileged automation.

CWL repositories and naruon retain their own product tests, authorization,
release, deployment, data-governance, and runtime responsibilities. The central
workflow owns only organization-level queue inspection and bounded repair
dispatch.

## Verification

Dependency-free static tests pin the hourly cron, one-hour retry default,
one-dispatch budget, single-flight concurrency, immutable called-workflow
checkout, ignored compatibility input, and least-privilege token boundary. The
exact PR head must also pass all central security, coverage, workflow-contract,
and independent-review gates before merge.

## References (APA 7th edition)

GitHub. (n.d.). *Contexts reference: Job context*. GitHub Docs. Retrieved August
4, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#job-context

GitHub. (n.d.). *Reusing workflow configurations*. GitHub Docs. Retrieved August
4, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

GitHub. (n.d.). *Reusing workflows*. GitHub Docs. Retrieved August 4, 2026, from
https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows
