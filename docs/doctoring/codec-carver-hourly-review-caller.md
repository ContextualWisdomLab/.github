# Codec-carver hourly review-repair caller

검토 기준일: **2026-08-17**

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/codec-carver` (omni-modal speech-and-video codec:
STT, speaker diarization, consented voiceprint, and conversion for LLM
input). The caller runs at minute 5, delegates to the product-neutral
central review-fix scheduler, inspects at most 50 open pull requests
targeting protected `main`, and dispatches at most one bounded repair
per heartbeat.

A paying buyer of the codec would feel live codec-carver pull requests
stalling while hourly NVIDIA NIM repair scanned only Clearfolio, DiskSage,
and fast-mlsirm. Live heads such as ContextualWisdomLab/codec-carver#435
(HMAC Unicode DoS), #437 (SQLite WAL journal), and #434 (search
performance) target `main` and never enter those other callers.

The caller does not implement review or mutation logic itself.
Codec-carver remains standalone; naruon consumes converted media without
owning the codec runtime. Privileged automation stays in
`ContextualWisdomLab/.github`.

## Root-cause analysis and remediation feasibility

The reusable worker performs exact-head root-cause analysis and tests
remediation feasibility before it edits. The reusable worker must:

1. Refetch the exact live head, base, reviews, checks, changed paths, and
   writer state.
2. Establish the causal chain rather than repeat the terminal symptom.
3. Enumerate materially distinct minimal remedies.
4. Reject remedies that lack writer authority, cross sealed paths, require
   unavailable credentials or protected-setting changes, violate stack
   order, cannot be verified, or do not alter the diagnosed cause.
5. Dispatch at most one feasible repair. Otherwise leave the tree
   unchanged.

A queued or pending check remains a merge blocker but is not itself a
code finding. The independent non-author approval remains an external
authorization gate and is never synthesized by the repair worker. The
worker cannot approve, merge, release, resolve review findings by
inference, change protection, or manufacture passing checks.

## Cadence and concurrency

The caller uses a single concurrency group and `cancel-in-progress: false`.
This preserves an in-flight bounded RCA instead of discarding codec
evidence when the next hourly heartbeat arrives. The reusable scheduler
cancels only its own superseded short queue scan.

The caller sets a **two-hour same-head retry floor**. Central OpenCode and
NVIDIA NIM work, plus codec conversion or HMAC verification analysis, can
legitimately approach two hours. An hourly redispatch of the same
unchanged head would create duplicate writer pressure rather than faster
remediation.

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
is the GitHub Secret `NVIDIA_NIM_API_KEY`; the caller does not receive or
forward it.

Before protected-main activation, the repository variable
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain the exact
`ContextualWisdomLab/codec-carver` target. Missing or mismatched
configuration fails before mutation credential materialization.

## Security, standalone operation, and modularity

The caller adds no codec-carver runtime dependency, database object,
network endpoint, tenant authority, or product credential. Codec-carver
continues to run as a standalone conversion service. Naruon and other CWL
services may consume its output, but they cannot weaken its exact-head,
approval, or security gates.

## Verification and rollback

Machine-checkable contracts require the exact target/base, minute 5
cadence, non-cancelling single-flight group, one dispatch, two-hour
retry floor, explicit secret mapping, read-only contents plus job-scoped
`id-token: write`, focused path-filter coverage, and absence of model or
Copilot credentials. Independent `pull_request`, `push`, and `compileall`
path blocks must each name the caller, doctoring, or contract they own.

After source integration, closure requires a scheduled or manual
protected-main consumer run proving the exact codec-carver repository and
`main` base. Source checks alone are not protected-main operational acceptance.
Merge still requires zero unresolved valid findings and a
qualifying independent non-author approval.

Rollback removes the codec-carver caller, its focused test, doctoring, and
central path-filter/documentation entries. It must not remove scheduler
dispatch validation or affect independent product callers.

## APA 7th references

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs.
Retrieved August 17, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August
17, 2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *Automatic token authentication*. GitHub Docs.
Retrieved August 17, 2026, from
https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication#permissions-for-the-github_token

MITRE. (2026). *CWE-250: Execution with unnecessary privileges*.
https://cwe.mitre.org/data/definitions/250.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating
the risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

NVIDIA. (n.d.). *NVIDIA NIM for large language models documentation*.
Retrieved August 17, 2026, from
https://docs.nvidia.com/nim/large-language-models/latest/

OpenCode. (n.d.). *OpenCode documentation*. Retrieved August 17, 2026,
from https://opencode.ai/docs/
