# naruon hourly review-repair caller

## Decision and operating boundary

The central repository owns a thin scheduled caller for
`ContextualWisdomLab/naruon`, the platform product. It runs at minute 11
each hour so it does not share a runner burst with Clearfolio (23),
DiskSage (37), or Inkspan (47). It calls the product-neutral
`pr-review-fix-scheduler.yml` with naruon's protected `develop` base, a
one-dispatch budget, and a one-hour same-head retry floor. Live naruon
change requests target `develop`, not `main`; a `main` caller would scan
an empty or wrong queue while buyer-facing platform PRs sat unrepaired.

The caller contains product identity, cadence, and explicit reusable-workflow
inputs only. Queue classification, exact-head binding, root-cause analysis,
remediation feasibility, retry markers, and repair dispatch remain central.
naruon continues to own its application, data, runtime, and release semantics.

## Authority and secret contract

The caller keeps `GITHUB_TOKEN` at `contents: read` and maps only
`PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN`. It never uses
`secrets: inherit`, receives `NVIDIA_NIM_API_KEY`, or introduces
`COPILOT_GITHUB_TOKEN`. CWE-269 forbids granting the caller the worker's
write or model privileges (MITRE, 2026). Model credentials remain scoped
to the separately reviewed repair worker.

Before protected-main activation of this control-plane caller, the
repository variable `OPENCODE_REPOSITORY_DISPATCH_TARGETS` must contain
the exact `ContextualWisdomLab/naruon` target. Missing or mismatched
configuration fails before mutation credential materialization. The
scanned naruon branch remains protected develop.

## Failure and recovery

A missing target allowlist entry, credential, or exact-head evidence is a
non-passing configuration state. Operators correct the bounded configuration
and rerun the unchanged protected source. Merge also retains every required
security check, zero unresolved valid findings, and a qualifying
independent non-author approval.

## Verification and rollback

Machine-checkable contracts require the exact target, minute 11 cadence,
non-cancelling single-flight group, one dispatch, one-hour retry floor, explicit
secret mapping, read-only permissions, and absence of model or Copilot
credentials.

Rollback removes the naruon caller, its focused test, doctoring, and the
associated central path-filter entries.

## APA 7th references

MITRE. (2026). *CWE-269: Improper privilege management*.
https://cwe.mitre.org/data/definitions/269.html

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 13, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-b). *Reuse workflows*. GitHub Docs. Retrieved August 13,
2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows
