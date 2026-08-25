# macOS utility packs hourly review-repair caller

검토 기준일: **2026-08-25**

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/macos_utility_packs`, the idempotent bootstrap that
turns a fresh Mac into an AI developer workstation (Brewfile packages,
Colima runtime, shared-skills sync with a JSON deny list, MCP merge,
doctor evidence). The caller runs at minute 44 — a fresh roster
allocation that avoids every documented slot — delegates to the
product-neutral central review-fix scheduler, inspects at most 50 open
pull requests targeting protected `develop`, and dispatches at most one
bounded repair per heartbeat.

An operator rebuilding a workstation would feel the deny-list and
doctor hardening stalling while hourly NVIDIA NIM repair scanned only
Clearfolio, DiskSage, and fast-mlsirm. Live work such as
ContextualWisdomLab/macos_utility_packs#3 (enforce the JSON skill deny
list blocking the homoglyph-named `re-d_data` prompt-injection payload)
and ContextualWisdomLab/macos_utility_packs#2 (complete macOS AI
bootstrap setup) targets `develop` and never enters those other
callers.

The caller does not implement review or mutation logic itself. The
bootstrap stays standalone; skills.sh, doctor, and MCP merge helpers
remain owned by the product repository. Privileged automation stays in
`ContextualWisdomLab/.github`.

## Root-cause analysis and remediation feasibility

The reusable worker performs exact-head root-cause analysis and tests
remediation feasibility before it edits. The reusable worker must:

1. Refetch the exact live head, base, reviews, checks, changed paths,
   and writer state.
2. Establish the causal chain rather than repeat the terminal symptom.
3. Enumerate materially distinct minimal remedies.
4. Reject remedies that lack writer authority, cross sealed paths,
   require unavailable credentials or protected-setting changes, violate
   stack order, cannot be verified, or do not alter the diagnosed cause.
5. Dispatch at most one feasible repair. Otherwise leave the tree
   unchanged.

A queued or pending check remains a merge blocker but is not itself a
code finding. The independent non-author approval remains an external
authorization gate and is never synthesized by the repair worker. The
worker cannot approve, merge, release, resolve review findings by
inference, change protection, or manufacture passing checks.

## Cadence and concurrency

The caller uses a single concurrency group and
`cancel-in-progress: false`. This preserves an in-flight bounded RCA —
for example a ShellCheck gate or Python 3.14 trace-coverage failure —
instead of discarding evidence when the next hourly heartbeat arrives.
The reusable scheduler cancels only its own superseded short queue scan.

The caller sets a **two-hour same-head retry floor**. Central OpenCode
and NVIDIA NIM work can legitimately approach two hours on full-suite
bootstrap verification. An hourly redispatch of the same unchanged head
would create duplicate writer pressure rather than faster remediation.

GitHub scheduled workflows can be delayed under load and execute only
from the default branch. The cron expression is a heartbeat, not a
real-time SLA.

## Credential and model boundary

The caller keeps workflow `GITHUB_TOKEN` at `contents: read` and grants
the reusable job `id-token: write` so the central scheduler can mint the
OpenCode GitHub App token from GitHub OIDC when the mapped PAT is absent
(GitHub, n.d.-c). It maps only `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN`. It never uses `secrets: inherit`, receives
`NVIDIA_NIM_API_KEY`, or introduces `COPILOT_GITHUB_TOKEN`. CWE-250
forbids executing the caller with write or model privileges it does not
need (MITRE, 2026).

Model execution remains inside the central worker. The model credential
is the GitHub Secret `NVIDIA_NIM_API_KEY`; the caller does not receive
or forward it.

Before protected-develop activation, the repository variable
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain the exact
`ContextualWisdomLab/macos_utility_packs` target. Missing or mismatched
configuration fails before mutation credential materialization.

## Security, standalone operation, and modularity

The caller adds no bootstrap runtime dependency, Homebrew formula,
network endpoint, or product credential. macos_utility_packs continues
to run standalone on any macOS 14+ host. The shared-skill ecosystem may
consume its deny-list pattern, but it cannot weaken its exact-head,
approval, or security gates.

## Verification and rollback

Machine-checkable contracts require the exact target/base, minute 44
cadence, non-cancelling single-flight group, one dispatch, two-hour
retry floor, explicit secret mapping, read-only contents plus job-scoped
`id-token: write`, focused path-filter coverage, and absence of model or
Copilot credentials. Independent `pull_request`, `push`, and
`compileall` path blocks must each name the caller, doctoring, or
contract they own.

After source integration, closure requires a scheduled or manual
protected-develop consumer run proving the exact macos_utility_packs
repository and `develop` base. Source checks alone are not
protected-develop operational acceptance. Merge still requires zero
unresolved valid findings and a qualifying independent non-author
approval.

Rollback removes the macos_utility_packs caller, its focused test,
doctoring, and central path-filter/documentation entries. It must not
remove scheduler dispatch validation or affect independent product
callers.

## APA 7th references

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs.
Retrieved August 25, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August
25, 2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *OpenID Connect reference*. GitHub Docs. Retrieved
August 25, 2026, from
https://docs.github.com/en/actions/reference/security/oidc

GitHub, Inc. (n.d.-d). *Automatic token authentication*. GitHub Docs.
Retrieved August 25, 2026, from
https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication#permissions-for-the-github_token

MITRE. (2026). *CWE-250: Execution with unnecessary privileges*.
https://cwe.mitre.org/data/definitions/250.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating
the risk of software vulnerabilities* (NIST Special Publication
800-218). https://doi.org/10.6028/NIST.SP.800-218

NVIDIA. (n.d.). *NVIDIA NIM for large language models documentation*.
Retrieved August 25, 2026, from
https://docs.nvidia.com/nim/large-language-models/latest/

OpenCode. (n.d.). *OpenCode documentation*. Retrieved August 25, 2026,
from https://opencode.ai/docs/
