# BandScope hourly review-repair caller

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

## Decision and operating boundary

The central repository owns a thin scheduled caller for
`ContextualWisdomLab/bandscope`. It runs at minute 53 each hour and calls the
product-neutral `pr-review-fix-scheduler.yml` for pull requests targeting
BandScope's protected `develop` branch. The offset avoids Clearfolio minute 23,
DiskSage minute 37, and the planned Inkspan minute 47 heartbeat.

The caller contains product identity, cadence, and explicit reusable-workflow
inputs only. Queue classification, exact-head/live-base binding, root-cause
analysis, remediation feasibility, retry markers, and repair dispatch remain
central. BandScope owns its application, evidence, data, runtime, accessibility,
and release semantics.

## Authority and secret contract

The caller keeps workflow `GITHUB_TOKEN` at `contents: read` and grants
the reusable job `id-token: write` so the central scheduler can mint the
OpenCode GitHub App token from GitHub OIDC when the mapped PAT is absent
(GitHub, n.d.-c). It maps only `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN`. It never uses `secrets: inherit`, receives
`NVIDIA_NIM_API_KEY`, or introduces `COPILOT_GITHUB_TOKEN`. CWE-250
forbids executing the caller with write or model privileges it does not
need (MITRE, 2026). Model credentials remain scoped to the separately
reviewed repair worker. The worker cannot approve, merge, release,
resolve review findings by inference, change protection, or manufacture
passing checks.

Before protected-main activation, the repository variable
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain the exact
`ContextualWisdomLab/bandscope` target. Missing or mismatched configuration
fails before mutation credential materialization. GitHub App installation and
both mapped credentials must remain limited to approved repositories.

## Failure and recovery

A missing target mapping, credential, protected base, or exact-head evidence is
a non-passing configuration state. Operators correct the bounded configuration
and rerun unchanged protected source; they do not widen credentials, inherit all
secrets, bypass review, or perturb a clean source head. A later heartbeat does
not cancel an in-flight decision. Same-head retry markers and the per-PR writer
lease prevent duplicate repair writers.

After source integration, closure requires a scheduled or manual protected-main
consumer run proving the exact BandScope repository and `develop` base. This
protected-main operational acceptance must also prove the
read-only caller token, bounded dispatch decision, and fail-closed allowlist and
credential behavior. Source checks alone are not protected-main operational
acceptance. Merge still requires zero unresolved valid findings and a
qualifying independent non-author approval.

## Verification and rollback

Machine-checkable contracts require the exact target/base, minute 53 cadence,
non-cancelling single-flight group, one dispatch, one-hour retry floor, explicit
secret mapping, read-only contents plus job-scoped `id-token: write`, focused
path-filter coverage, and absence of model or Copilot credentials. The full
owned suite and hosted security and review gates must pass on the unchanged
exact head.

Rollback removes the BandScope caller, its focused test, doctoring, and central
path-filter/documentation entries. It must not remove scheduler dispatch
validation or affect independent product callers.

## APA 7th references

MITRE. (2026). *CWE-250: Execution with unnecessary privileges*.
https://cwe.mitre.org/data/definitions/250.html

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 12, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August 12,
2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.-c). *Automatic token authentication*. GitHub Docs.
Retrieved August 17, 2026, from
https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication#permissions-for-the-github_token

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1* (NIST SP 800-218).
https://doi.org/10.6028/NIST.SP.800-218
