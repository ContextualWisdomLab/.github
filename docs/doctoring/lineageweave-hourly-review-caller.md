# LineageWeave hourly review-repair caller

## Decision

The organization control plane invokes its existing review-repair scheduler for
`ContextualWisdomLab/LineageWeave` at minute 4 of every hour. The caller scans
all pull-request bases because LineageWeave uses stacked pull requests, but it
dispatches at most one repair and waits two hours before retrying an unchanged
head. A new heartbeat never cancels an in-flight diagnosis.

The caller is deliberately thin. It does not approve, merge, release, or change
a review-agent identity. It does not create product work. The reusable
scheduler refetches the current head, reviews, threads, checks, and writer lease
before dispatching the existing OpenCode repair worker. Independent current-head approval
and all protected checks remain mandatory.

## Credential and model boundary

The workflow token is read-only. The caller maps only the established
`PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` inputs and permits the
reusable scheduler's existing OIDC fallback; it never inherits all secrets.
It does not receive a model credential or provider endpoint and does not use
`COPILOT_GITHUB_TOKEN`.

Model execution remains inside the reviewed central worker and crosses its
`contextual-orchestrator` boundary. This caller neither selects a provider nor
changes contextual-orchestrator discovery, routing, or review-agent secrets.

## Product-gap continuation boundary

This caller closes the missing hourly stacked-PR repair path only. Product-gap
development after the PR queue empties remains owned by the organization
commercial-readiness coordinator and an explicitly opted-in, bounded
repository development entrypoint. LineageWeave does not currently publish
that entrypoint, and recent coordinator runs failed before inventory because
their maintainer credential was unavailable. Therefore this workflow is not
evidence that autonomous product-gap development is operational.

## Verification and rollback

Contract tests bind the cadence, stack scope, dispatch budget, retry floor,
permissions, explicit secret mapping, absent model credentials, reusable
scheduler path, and focused quality-workflow coverage. A scheduled run proves
only accepted dispatch after live state validation; it does not prove a repair,
approval, merge, release, or product increment.

Rollback is removal of this caller after confirming another enabled workflow
owns the same LineageWeave writer lease. Do not run duplicate scheduled writers.

## APA 7th references

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. Retrieved
August 28, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

GitHub. (n.d.). *Events that trigger workflows: Schedule*. Retrieved August
28, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub. (n.d.). *Reuse workflows*. Retrieved August 28, 2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reusing-workflows

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218
