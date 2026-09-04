# Dependency-review public required-workflow 403 — 2026-09-05

## Incident evidence

`ContextualWisdomLab/ConceptWeave` PR #1 exact Foundation head `8e8783286eac7567803568d9a91010daaf028074` reached the organization-required `Security Scan` on hosted `ubuntu-24.04`. Run `33886162808`, job `101108147137` checked out the exact head and failed in `Check dependency review support` before the pinned dependency-review action ran.

The preflight observed:

- repository `ContextualWisdomLab/ConceptWeave`;
- base `f4f440dd58c77d7cd90dff8a1eb2eeb9a9940425`;
- head `8e8783286eac7567803568d9a91010daaf028074`;
- repository visibility `public` and repository metadata `fork=false`;
- job token permissions including `Contents: read` and `PullRequests: read`;
- dependency-review REST comparison HTTP `403` with curl exit `0`.

The existing preflight intentionally discarded the response body and did not retain request/rate headers, so the run cannot distinguish an authorization-service anomaly, secondary rate limiting, or another GitHub-side condition. It correctly failed closed; the failure must not be relabelled as GREEN or bypassed.

## External contract

GitHub documents `GET /repos/{owner}/{repo}/dependency-graph/compare/{basehead}` as requiring only repository `Contents: read` for fine-grained tokens and as callable without authentication for public resources. Its documented `403` cases are a private repository without the required security entitlement or a fork. GitHub also documents the dependency review action as available for public repositories and its standard workflow example grants only `contents: read`.

Primary sources:

- https://docs.github.com/en/rest/dependency-graph/dependency-review#get-a-diff-of-the-dependencies-between-commits
- https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review
- https://docs.github.com/en/code-security/concepts/supply-chain-security/supply-chain-security

## Decision

Keep the hard gate fail closed. Do not reinterpret HTTP 403 as supported and do not skip dependency review. For a public non-fork target only, the owner workflow must make a bounded same-token re-observation before terminal rejection and retain bounded non-secret GitHub request/rate metadata (`X-GitHub-Request-Id`, `Retry-After`, `X-RateLimit-Remaining`) so a repeated 403 can be classified from exact hosted evidence. Private/internal repositories and forks keep the existing strict behavior. Only a final HTTP 200 may set `supported=true` and reach the pinned dependency-review action.

This is deliberately narrower than an anonymous fallback: although the REST endpoint permits unauthenticated public reads, the pinned action itself defaults to `github.token`. An anonymous preflight could therefore pass while the actual action still fails with the same token, producing false support evidence.

## RED / GREEN

RED is the ConceptWeave hosted failure above plus the owner regression contract in `tests/test_dependency_review_public_required_workflow_403.py`. GREEN requires the central required workflow to satisfy that contract, retain final non-200 fail-closed semantics, obtain an unchanged exact owner-head CI result, then produce a fresh ConceptWeave consumer run where the dependency-review action itself reaches a terminal result. A preflight-only 200, predecessor success, manual override, or rerun of unchanged broken workflow code is not GREEN.
