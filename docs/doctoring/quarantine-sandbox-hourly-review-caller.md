# Quarantine Sandbox Runtime hourly review-repair caller

검토 기준일: **2026-08-18**

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/quarantine-sandbox-runtime`, the credential-free and
source-agnostic artifact-analysis leaf used by authorized security and
composition products. The caller runs at minute 14, delegates to the
product-neutral central review-fix scheduler, inspects at most 50 open pull
requests targeting protected `develop`, and dispatches at most one bounded
repair per heartbeat.

The immediate buyer-perceivable gap is queue starvation: the repository has a
buyer-facing contract PR and a Rust runtime-foundation PR, but it was absent
from the existing product-specific hourly callers. Security review latency is
not permission to bypass approval or checks; it is a reason to give the exact
repository a bounded, auditable repair heartbeat.

The caller does not implement review or mutation logic. Quarantine Sandbox
Runtime remains independently deployable. Wardnet, naruon, gyeot, and other
authorized hosts may consume the published evidence contract without owning the
runtime. Privileged automation remains in `ContextualWisdomLab/.github`.

## Root-cause analysis and remediation feasibility

The reusable worker performs exact-head root-cause analysis and tests
remediation feasibility before editing. It must:

1. Refetch the live head, base, reviews, unresolved threads, checks, changed
   paths, stack relationships, and active writer state.
2. Establish the first causal boundary instead of repeating a terminal failed
   check or review message.
3. Enumerate materially distinct minimal remedies.
4. Reject remedies that lack writer authority, cross the sealed path set,
   require unavailable credentials or protected-setting changes, violate stack
   order, cannot be verified, or do not change the diagnosed cause.
5. Dispatch at most one feasible repair; otherwise leave the branch unchanged
   and continue productive non-conflicting work.

A queued check remains a merge blocker but is not a code defect. The independent non-author approval remains an external authorization gate and is never synthesized
by the repair worker. The worker cannot approve, merge, release, weaken branch
protection, reinterpret a missing sandbox capability as success, or manufacture
passing evidence.

## Cadence and concurrency

The caller uses one repository-scoped concurrency group and
`cancel-in-progress: false`. A later heartbeat must not discard an in-flight
security RCA. The reusable scheduler may cancel only a superseded short queue
scan.

The caller sets a **two-hour same-head retry floor**. OpenCode/NVIDIA NIM review
and hostile-artifact boundary analysis may legitimately take longer than one
hour. Re-dispatching the same unchanged head every hour would create duplicate
writer pressure.

GitHub scheduled workflows run only from the default branch and can be delayed
under Actions load. Minute 14 avoids the start-of-hour load peak and the existing
CWL product caller minutes. The cron expression is a heartbeat, not a real-time
SLA (GitHub, Inc., n.d.-a).

## Credential and model boundary

The caller keeps workflow `GITHUB_TOKEN` at `contents: read`. Only the reusable
job receives `id-token: write`, enabling the central scheduler to request a
GitHub OIDC token when its reviewed credential chain requires one (GitHub, Inc.,
n.d.-b). The caller maps only `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN`; it never uses `secrets: inherit`, receives
`NVIDIA_NIM_API_KEY`, or introduces `COPILOT_GITHUB_TOKEN`.

Model execution and the NVIDIA credential remain inside the separately reviewed
central worker. This caller holds no model secret and cannot run arbitrary pull
request content. Limiting privileges follows CWE-250 and the NIST SSDF practice
of protecting software-development environments and artifacts (MITRE, 2026;
Souppaya et al., 2022).

Before protected-main activation, `OPENCODE_REPOSITORY_DISPATCH_TARGETS` must
contain the exact `ContextualWisdomLab/quarantine-sandbox-runtime` target.
Missing or mismatched configuration fails before mutation credentials are
materialized.

## Product and MSA boundary

The scheduler may repair code or documentation inside the target PR's verified
scope. It does not move these product authorities:

- Quarantine Sandbox Runtime owns artifact-analysis evidence.
- Wardnet owns WAF/IDS and SOC response policy.
- Naruon owns email admission and mailbox state.
- EgressWeave owns controlled outbound HTTP.
- The calling product owns final maliciousness judgment, incident action, and
  retention.

The caller adds no runtime dependency, database object, network endpoint,
artifact-execution authority, tenant authority, or product credential. The
sandbox runtime remains a standalone leaf and composition hubs consume its
published contract.

## Verification and operational acceptance

Machine-checkable contracts require:

- exact repository and `develop` base;
- minute 14 hourly cadence;
- non-cancelling repository-scoped concurrency;
- at most one dispatch and a two-hour same-head retry floor;
- read-only workflow contents plus job-scoped `id-token: write`;
- explicit scheduler-secret mapping;
- absence of `NVIDIA_NIM_API_KEY`, `COPILOT_GITHUB_TOKEN`, and `secrets: inherit`;
- independent `pull_request`, `push`, and `compileall` coverage of the caller,
  focused test, and doctoring document; and
- no product name hard-coded in the reusable scheduler.

After merge, a scheduled protected-default-branch run must prove the exact
target and base. Source checks alone are not protected-main operational
acceptance. Product PR merge still requires exact-head required checks,
resolution of every valid review finding, and qualifying independent approval.

Rollback removes only this caller, its focused test, doctoring, and central
quality-path entries. It must not remove the reusable scheduler or alter another
product caller.

## APA 7th references

GitHub, Inc. (n.d.-a). *Troubleshooting workflows*. GitHub Docs. Retrieved
August 18, 2026, from
https://docs.github.com/en/actions/how-tos/troubleshoot-workflows

GitHub, Inc. (n.d.-b). *OpenID Connect reference*. GitHub Docs. Retrieved
August 18, 2026, from
https://docs.github.com/en/actions/reference/security/oidc

GitHub, Inc. (n.d.-c). *Reuse workflows*. GitHub Docs. Retrieved August 18,
2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

MITRE. (2026). *CWE-250: Execution with unnecessary privileges*.
https://cwe.mitre.org/data/definitions/250.html

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
