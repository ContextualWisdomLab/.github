# Noema token-lifetime quality stale-run retirement

## Status

Proposed on the repair branch pending exact-current-head protected review and Checks. This document is evidence/doctoring, not merge authority.

## Incident and root cause

On 2026-09-02, pushing `ContextualWisdomLab/.github#1717` from predecessor head `5b8badc3b9088a5845abc447ed75bf2d9a99031d` to current-main reconciliation head `aeae0c681b66c2e6e9b98d13e47d684eb350b0a8` correctly retired the predecessor runs for Security Scan, OSV-Scanner PR, Semgrep, CodeQL, Strix Changed Path Quality CI, contextual-orchestrator review-repair quality, Python Security, organization commercial readiness, Secret Scan, Scorecard, SBOM, OpenCode Rust coverage, and exact-artifact SBOM quality. The predecessor `Noema Reviewer Token Lifetime CI` run `33621482031`, however, remained queued while the new-head run `33622618082` was also queued.

The owner workflow `.github/workflows/noema-token-lifetime-quality-ci.yml` had no `concurrency` contract at all. A PR synchronize therefore created a new expensive validation without retiring the obsolete queued/in-progress run for the same repository + PR lineage. This directly violated the control-plane stale-Actions contract and consumed scarce shared Actions capacity.

## RED → repair contract

A regression was committed first at `181889f260d3c0f5a048a52f58e470bfb9090b64`. It requires this pull-request workflow to use a repository + PR stable concurrency group, deliberately excludes both `github.event.pull_request.head.sha` and `github.sha`, and requires `cancel-in-progress: true`. The unmodified protected-main workflow fails immediately because it contains no `concurrency:` block.

The production repair adds only the missing PR-stable concurrency boundary:

- repository identity: `github.event.pull_request.base.repo.full_name`;
- PR identity: `github.event.pull_request.number`;
- no head SHA in the group;
- `cancel-in-progress: true`.

This quality gate executes deterministic token-lifetime tests rather than a long semantic reviewer, so preserving superseded in-progress work has no safety benefit. Native GitHub concurrency cancellation is the least-privilege mechanism: it needs no `actions: write`, privileged cancellation token, untrusted-head execution, or custom stale-run API code.

## Invariants preserved

The workflow remains `pull_request`-scoped with the same path filter, `contents: read`, `ubuntu-24.04`, exact source checkout, hash-locked CI dependency installation, token-lifetime/two-phase/App-identity pytest targets, compile verification, and `git diff --check`. This change does not alter Noema verdict semantics, contextual-orchestrator routing, provider/model selection, protected branch requirements, or review authority.

## Verification required before merge

1. Re-read the exact PR head and workflow text.
2. Prove the regression is GREEN on that exact head.
3. Confirm a subsequent synchronize retires the older `Noema Reviewer Token Lifetime CI` queued/in-progress run and leaves only the current-head authoritative lineage.
4. Re-fetch reviews, unresolved threads, and required/security Checks; merge only through ordinary protection unless the strict independently verified `QUEUE_SATURATION_CHICKEN_EGG` boundary is freshly satisfied.
