# Inkspan hourly review-repair caller

검토 기준일: **2026-08-24**

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/inkspan`, the standalone TipTap/ProseMirror Markdown and
HTML editor module with bounded Office import, base64 image conversion,
accessibility, and host-integration contracts. The caller runs at minute 47,
delegates to the product-neutral central review-fix scheduler, inspects at most
50 open pull requests targeting protected `main`, and dispatches at most one
bounded repair per heartbeat.

The repository had 52 open `main` pull requests at this decision snapshot.
Buyer-visible work included ContextualWisdomLab/inkspan#373 (dependency
security), ContextualWisdomLab/inkspan#372 (product-gap evidence),
ContextualWisdomLab/inkspan#362 (editor accessibility), and
ContextualWisdomLab/inkspan#299 (stacked exact-head gates). Leaving this queue
outside the dedicated hourly repair frontier makes reviewed editor safety,
accessibility, and release fixes wait behind unrelated products.

The caller does not implement product, review, or mutation logic. Inkspan keeps
ownership of editor state, document formats, host APIs, design tokens,
Storybook inventory, persistence, and release semantics. Privileged automation
stays in `ContextualWisdomLab/.github`, and consumers can continue importing
Inkspan as a module without the central repository at runtime.

## Root-cause analysis and remediation feasibility

The reusable worker performs exact-head root-cause analysis and tests
remediation feasibility before it edits. The reusable worker must:

1. Refetch the exact live head, base, reviews, checks, changed paths, stack
   dependencies, and writer state.
2. Establish the causal chain rather than repeat a terminal symptom.
3. Enumerate materially distinct minimal remedies and prefer existing project,
   platform, or dependency behavior before adding code.
4. Reject remedies that lack writer authority, cross sealed paths, require
   unavailable credentials or protected-setting changes, violate stack order,
   cannot be verified, or do not alter the diagnosed cause.
5. Dispatch at most one feasible repair; otherwise leave the tree unchanged and
   continue with another eligible head.

A queued or pending check remains a merge blocker but is not itself a source
finding. The independent non-author approval remains an external authorization
gate and is never synthesized by the repair worker. The worker cannot approve,
merge, release, resolve review findings by inference, change protection, or
manufacture passing checks.

## Cadence and concurrency

The caller uses its own concurrency group and `cancel-in-progress: false`. A
new heartbeat therefore cannot discard an editor-safety RCA or exact-head test
run already in progress. The reusable scheduler may cancel only its own
superseded short queue scan.

The caller sets a **two-hour same-head retry floor**. Central OpenCode, Strix,
Noema, and NVIDIA NIM work can legitimately exceed one hour, and the user has
explicitly prioritized accuracy over latency. An hourly heartbeat still finds
new heads immediately, while an unchanged head cannot create duplicate writer
pressure before the active evidence window has elapsed.

GitHub scheduled workflows execute from the default branch and may be delayed
under load. The cron expression is a durable heartbeat rather than a real-time
service-level promise (GitHub, n.d.-a).

## Credential and model boundary

The caller keeps workflow `GITHUB_TOKEN` at `contents: read` and grants the
reusable job `id-token: write` so the central scheduler can exchange GitHub OIDC
for its OpenCode GitHub App token when a mapped PAT is unavailable (GitHub,
n.d.-c). It maps only `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN`, never uses `secrets: inherit`, never receives
`NVIDIA_NIM_API_KEY`, and never introduces `COPILOT_GITHUB_TOKEN`.

Model discovery, provider selection, reasoning effort, and LLM execution remain
inside the separately reviewed central worker and contextual-orchestrator
boundary. The thin caller contains no model name, provider API, temperature,
fallback list, or prompt. CWE-250 forbids giving this read-only scheduler
surface write or model privileges it does not need (MITRE, 2026).

Before protected-main activation, the repository variable
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain the exact
`ContextualWisdomLab/inkspan` target. A missing or mismatched value fails before
mutation credential materialization. GitHub App installation and mapped
credentials must also remain limited to approved repositories.

## Security, standalone operation, and modularity

The caller adds no Inkspan runtime dependency, database object, network
endpoint, tenant authority, customer document, or product credential. It never
executes pull-request code with mutation secrets. Inkspan remains independently
buildable, testable, releasable, and consumable by LineageWeave, naruon, or
other hosts; the central repository only coordinates repository maintenance.

The control follows SSDF's separation of protected build/automation controls
from untrusted contribution content and records a machine-verifiable least-
privilege boundary rather than relying on operator memory (NIST, 2022).

## Verification and rollback

Machine-checkable contracts require the exact repository and `main` base,
minute-47 cadence, non-cancelling single-flight group, one-dispatch budget,
two-hour retry floor, explicit secret mapping, read-only contents plus
job-scoped `id-token: write`, focused path-filter coverage, and absence of model
or Copilot credentials. Independent `pull_request`, `push`, and `compileall`
blocks each name the caller, doctoring, or contract they own.

After source integration, closure requires a scheduled protected-main consumer
run proving the exact Inkspan target and `main` base, read-only caller token,
OIDC/PAT fail-closed behavior, and bounded dispatch decision. Source checks
alone are not protected-main operational acceptance. Merge still requires
terminal protected checks, zero unresolved valid findings, and a qualifying
independent non-author approval.

Rollback removes the Inkspan caller, its focused test, doctoring, and central
path-filter/documentation entries. It must not remove scheduler validation or
affect any independent product caller.

## APA 7th references

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 24, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August 24,
2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *OpenID Connect*. GitHub Docs. Retrieved August 24,
2026, from https://docs.github.com/en/actions/concepts/security/openid-connect

MITRE. (2026). *CWE-250: Execution with unnecessary privileges*.
https://cwe.mitre.org/data/definitions/250.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218
