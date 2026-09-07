# ADR-0025: Fail closed on ambiguous Dependency Review authority and preserve caller permissions

- **Status:** Proposed
- **Date:** 2026-09-02
- **Scope:** `.github/workflows/dependency-review.yml`, its thin product callers, and the reusable-workflow security contract
- **Supersedes:** ADR-0024 only where ADR-0024 treated HTTP 403/404 as confirmed Dependency Graph unavailability or showed callers without an explicit permission envelope

## Problem

The protected-main consolidation from #1724 exposed two independent security-contract defects.

First, the reusable workflow classified Dependency Graph compare HTTP 403/404 as `available=false` and therefore skipped the blocking Dependency Review action. Those responses are not authoritative proof that the feature is unavailable: they can also be authorization or policy failures. Turning an ambiguous authorization-shaped response into success silently removes a security gate.

Second, the migration examples and thin callers omitted the permission envelope that the original repository-local workflows carried. GitHub reusable workflows cannot elevate `GITHUB_TOKEN` permissions through the call chain. A called workflow may maintain or reduce permissions granted by the caller, but it cannot manufacture `pull-requests: read` when the caller did not grant it. The result is a workflow-level `startup_failure` before any job is created.

## Constraints

1. Dependency Review remains a distinct hard gate; OSV-Scanner, Scorecard, or another scanner cannot substitute for an ambiguous Dependency Review failure.
2. The called workflow needs only `contents: read` and `pull-requests: read`; no write permission is introduced.
3. Product callers remain thin and repository-owned. They keep repository-specific trigger, severity, allowlist, and `continue_on_error` policy.
4. Consumers pin the reusable workflow to an immutable protected-main commit after this proposal is merged. `@main`, branch URLs, and unmerged PR heads are not production authority.
5. Non-`pull_request` invocations may skip because they lack an exact PR base/head pair; pull requests fail closed unless the comparison endpoint returns HTTP 200.

## Considered alternatives

### Treat 403/404 as feature unavailable

Rejected. The status code alone cannot distinguish a genuinely unavailable Dependency Graph from denied authorization/policy. A false negative here converts a required security control into a warning.

### Infer support from repository visibility or GHAS assumptions

Rejected. Visibility is not a capability proof and was already the weaker design ADR-0024 replaced.

### Rely on the called workflow's `permissions:` block

Rejected as insufficient. GitHub does not let a reusable workflow elevate permissions beyond the caller's grant. The called workflow still declares its least-privilege ceiling, but each thin caller must explicitly grant the same read scopes.

### Grant broader token permissions globally

Rejected. It increases blast radius and hides a caller-contract defect instead of repairing it.

## Decision

1. For `pull_request`, the Dependency Graph compare preflight sets `available=true` only on HTTP 200. Every other HTTP status is emitted with an error and terminates the job nonzero.
2. Remove the pull-request "Dependency graph unavailable" success path. No alternate scanner is described as replacement authority.
3. Keep the called workflow at `contents: read` + `pull-requests: read` and require every thin caller to declare at least those same scopes explicitly.
4. Make the executable central contract fail when the canonical caller example omits either required scope.
5. Replace the mutable `@main` caller example with an immutable `<protected-main-commit-sha>` placeholder. After merge, consumers pin the resulting protected-main SHA.

## Exact evidence

- #1725 first RED: `cb07b8bb28ef9d3a147cc966a0c70654d132da1d`; first production repair: `31f60e532e135008cabd09fcddd46a53062b0ea0`.
- Permission-envelope RED: `ee0f1ce544965772775b590050e40476df4ea8f6`; it changes only the contract and requires the missing caller permission example.
- Permission-envelope production repair: `ca3bdbd210de988ccd31f7fb96d3a97adfdb9bff`.
- `newsdom-api#784@1623977e6c37c78cb1a94a7a48c48f6d02cac86c`: run `33622976911`, `startup_failure`, zero jobs, reusable workflow immutably resolved to `.github@0bcd22d8bb07650aafb0a8f116e4c2bbb8744f03`.
- `mightyETL#330@65efdf7b4064df5b9811c0403defb707e6efbc02`: run `33623035969`, `startup_failure`, zero jobs.
- Consumer permission repairs then produced materialized current-head runs: newsdom-api `9a798d5ac7b9b295a1accb2327fc76611352290f` run `33623818000`; mightyETL `4576f863ede9fca0673d6cce5ae8a4093246f5ab` run `33623854807`; scopeweave `db8b8ed6d36a6dc6cc1d07255a7a9a86bc88bf4f` run `33623761776`; Argos #557 `ee4c5dd326977407435b0f2425fdecebc34a810f` run `33623867278`.

Hosted exact-current-head Checks and independent review remain required before this ADR may become Accepted.

## Consequences and follow-up

- A missing or denied Dependency Graph comparison is visible as a blocking failure instead of silent coverage loss.
- Caller permission omissions become an executable contract defect rather than an undocumented deployment prerequisite.
- The central workflow still cannot repair a consumer's omitted permissions by itself; each consumer must carry the explicit read-only envelope and later bump its immutable reusable-workflow pin to the protected-main SHA that contains this decision.
- #1643 remains a separate diagnostic lane for the required Security Scan path and is not evidence transfer for this reusable Dependency Review gate.

## References

GitHub. (n.d.). *Reusing workflow configurations*. GitHub Docs. https://docs.github.com/actions/using-workflows/reusing-workflows

GitHub. (n.d.). *Use GITHUB_TOKEN for authentication in workflows*. GitHub Docs. https://docs.github.com/actions/security-guides/automatic-token-authentication
