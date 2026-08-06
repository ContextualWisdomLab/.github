# Security scan exact-head evidence

## Decision

The central `Security Scan` workflow treats the literal pull-request head as the only valid repository-scanner input. GitHub's `pull_request` event normally exposes a generated merge revision through `GITHUB_SHA`; that revision is useful for integration testing but cannot prove that Trivy or Scorecard scanned the exact current contributor head required by CWL authorization policy.

The dependency-review support checkout, Trivy filesystem scan, and Scorecard posture scan therefore set both:

```yaml
repository: ${{ github.event.pull_request.head.repo.full_name }}
ref: ${{ github.event.pull_request.head.sha }}
```

Persisted checkout credentials remain disabled. Fork pull requests are read through their explicit head repository and immutable commit SHA; no write credential is added.

## Durable SARIF identity

Scanning the head is insufficient when durable code-scanning evidence is attributed to a different revision. Trivy and Scorecard uploads explicitly bind:

```yaml
ref: refs/pull/${{ github.event.pull_request.number }}/head
sha: ${{ github.event.pull_request.head.sha }}
```

GitHub's code-scanning API requires both a full Git reference and the commit SHA to which an uploaded analysis relates. The pair above states that the SARIF describes the pull-request head, not the generated merge commit.

## Preserved security behavior

This change does not alter scanner versions, vulnerability severities, Trivy's fixable Medium-or-higher hard gate, dependency-review thresholds, Scorecard's soft posture role, SARIF sanitation, permissions, or the existing OSV base-versus-head comparison. It only makes scanner input and result identity consistent.

The workflow remains fail closed for absent scanner output and actionable findings. SARIF upload failures remain separately visible without suppressing the repository-local Trivy finding gate. A queued, cancelled, skipped, failed, missing, or predecessor-head run is not current-head evidence.

## Verification

`tests/test_security_scan_exact_head.py` verifies literal-head checkout for all three affected jobs. `tests/test_security_scan_sarif_exact_head.py` verifies durable Trivy and Scorecard SARIF attribution. The dedicated read-only quality workflow checks out the literal PR head, compiles both contracts, and executes them without package installation.

The initiating DiskSage evidence was Security Scan run `31070907732`, whose Trivy job log checked out `refs/remotes/pull/137/merge` rather than DiskSage PR #137 head `87ac0e08cceed3d1a766da13a8f8123912178192`. That result remains historical merge-tree evidence and is not reclassified as exact-head proof.

## Rollback

Rollback requires an independently reviewed revert and fresh exact-head security evidence. Do not restore implicit checkout or automatic SARIF revision detection unless an equally strict mechanism proves that the scanned filesystem, SARIF `ref`, and SARIF `sha` all identify the same current pull-request head.

## APA 7th references

GitHub. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub. (n.d.). *REST API endpoints for code scanning*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/rest/code-scanning/code-scanning

GitHub. (n.d.). *Uploading CodeQL analysis results to GitHub*. GitHub Docs. Retrieved August 6, 2026, from https://docs.github.com/en/enterprise-cloud@latest/code-security/tutorials/customize-code-scanning/upload-results
