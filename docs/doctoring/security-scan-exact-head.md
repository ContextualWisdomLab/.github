# Security scan exact-head evidence

## Decision

The central `Security Scan` workflow treats the literal pull-request head as the only valid repository-scanner input. GitHub's `pull_request` event normally exposes a generated merge revision through `GITHUB_SHA`; that revision is useful for integration testing but cannot prove that Trivy or Scorecard scanned the exact current contributor head required by CWL authorization policy.

The dependency-review support checkout, Trivy filesystem scan, and Scorecard posture scan therefore set both:

```yaml
repository: ${{ github.event.pull_request.head.repo.full_name }}
ref: ${{ github.event.pull_request.head.sha }}
```

Persisted checkout credentials remain disabled. Fork pull requests are read through their explicit head repository and immutable commit SHA; no write credential is added.

## Dependency-review availability is evidence, not an optimization

Dependency review is a hard supply-chain gate. The support probe compares the exact pull-request base SHA with the exact pull-request head SHA through GitHub's dependency-review API. Only HTTP `200` is accepted as evidence that the pinned `actions/dependency-review-action` may execute. HTTP `403`, `404`, `000`, an empty or malformed status, a transport failure, timeout, or any other unexpected probe result is **not** a clean dependency review and fails the job closed.

The failure diagnostic records only the repository identifier, exact base SHA, exact head SHA, and HTTP status. The API response body is discarded rather than printed because it is unnecessary for the authorization decision and can contain operational details that do not belong in a public workflow log. Authentication material is never included in the diagnostic.

A dependency-neutral path classifier is not a substitute for dependency-review evidence. In particular, the workflow must not translate an unavailable API into `not-applicable` merely because another mechanism believes the current diff contains no dependency change. OSV, Trivy, CodeQL, Semgrep, Secret Scan, Scorecard, and Dependabot remain independent controls; none semantically replaces the dependency-diff gate.

## Operator remediation for an unavailable gate

For a public GitHub.com repository, a `403` or `404` from the dependency-review comparison endpoint is treated as a repository or organization configuration problem until evidence proves otherwise. An operator should verify that the dependency graph and the GitHub security features required for dependency review are enabled for the repository and organization, that organization policy permits the endpoint, and that the workflow's read-only token receives the documented access needed by the dependency-review API and action. Rerun only after the capability or policy path is corrected; do not weaken the workflow to manufacture a green check.

Private or internal repositories can have different product-entitlement and policy requirements. Any exception for those repository classes must be designed as an explicit organization policy with independently reviewable entitlement evidence. It must not be inferred from a failed probe and must not weaken the public-repository canary semantics.

## Durable SARIF identity

Scanning the head is insufficient when durable code-scanning evidence is attributed to a different revision. Trivy and Scorecard uploads explicitly bind:

```yaml
ref: refs/pull/${{ github.event.pull_request.number }}/head
sha: ${{ github.event.pull_request.head.sha }}
```

GitHub's code-scanning API requires both a full Git reference and the commit SHA to which an uploaded analysis relates. The pair above states that the SARIF describes the pull-request head, not the generated merge commit.

## Preserved security behavior

This change does not alter scanner versions, vulnerability severities, Trivy's fixable Medium-or-higher hard gate, dependency-review thresholds, Scorecard's soft posture role, SARIF sanitation, permissions, or the existing OSV base-versus-head comparison. It makes scanner input and result identity consistent and makes unavailable dependency-review evidence an explicit hard failure instead of a green skip.

The workflow remains fail closed for absent scanner output and actionable findings. SARIF upload failures remain separately visible without suppressing the repository-local Trivy finding gate. A queued, cancelled, skipped, failed, missing, or predecessor-head run is not current-head evidence.

## Verification

`tests/test_security_scan_exact_head.py` verifies literal-head checkout and the rule that only an HTTP `200` support probe may reach dependency review. It also rejects the former `supported=false` / skip path and response-body logging. `tests/test_security_scan_sarif_exact_head.py` verifies durable Trivy and Scorecard SARIF attribution. The dedicated read-only quality workflow checks out the literal PR head, compiles both contracts, and executes them without package installation.

The initiating DiskSage evidence was Security Scan run `31070907732`, whose Trivy job log checked out `refs/remotes/pull/137/merge` rather than DiskSage PR #137 head `87ac0e08cceed3d1a766da13a8f8123912178192`. That result remains historical merge-tree evidence and is not reclassified as exact-head proof.

The dependency-review availability regression was reproduced on the public EgressWeave canary: a support probe returned HTTP `403`, the former workflow marked the hard action skipped, and the aggregate Security Scan still concluded success. That historical result is unavailable dependency-review evidence, not proof of a clean dependency diff.

## Rollback

Rollback requires an independently reviewed revert and fresh exact-head security evidence. Do not restore implicit checkout, automatic SARIF revision detection, or a fail-open dependency-review support path unless an equally strict mechanism proves the same authorization properties. In particular, never convert `403`, `404`, transport failure, or another unavailable probe outcome into a successful hard gate.

## APA 7th references

GitHub. (n.d.). *Dependency review*. GitHub Docs. Retrieved August 7, 2026, from https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review

GitHub. (n.d.). *REST API endpoints for dependency review*. GitHub Docs. Retrieved August 7, 2026, from https://docs.github.com/en/enterprise-cloud@latest/rest/dependency-graph/dependency-review

GitHub. (n.d.). *Customizing your dependency review action configuration*. GitHub Docs. Retrieved August 7, 2026, from https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/customize-dependency-review-action

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *REST API endpoints for code scanning*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/rest/code-scanning/code-scanning

GitHub. (n.d.). *Uploading CodeQL analysis results to GitHub*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/enterprise-cloud@latest/code-security/tutorials/customize-code-scanning/upload-results
