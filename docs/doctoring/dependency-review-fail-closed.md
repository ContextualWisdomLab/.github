# Dependency review fail-closed operations

Status: `active_pr` until the matching workflow and regression contract are present on protected `main`; thereafter `implemented_on_protected_main`.

## Decision

Dependency review is a hard supply-chain gate. The central workflow accepts only HTTP `200` from GitHub's exact `BASE_SHA...HEAD_SHA` comparison before invoking the immutably pinned dependency-review action. A `403`, `404`, empty or malformed status, timeout, transport failure, truncated exchange, or other unexpected outcome is unavailable evidence and fails closed.

Before any compare request, the support probe also validates the evidence identity. Base and head must be immutable 40- or 64-character hexadecimal Git object IDs, and the repository must be exactly one `owner/name` pair. The owner and name path components may not be the RFC 3986 dot-segment sentinels `.` or `..`; `ContextualWisdomLab/.github` remains valid because `.github` is an ordinary repository name, not a dot segment. This prevents a named ref or path-normalized repository value from changing what object the comparison actually addresses.

The support probe has a 10-second connection limit and 30-second total limit. It preserves curl's transport exit code separately from the bounded HTTP status and requires transport exit `0` plus exact HTTP `200`. It discards the response body and logs only repository identity, exact base/head revisions, the normalized HTTP status, and the numeric transport exit. Credentials and response bodies are never diagnostic output.

RFC 9110 §15.3.1 defines `200` as a completed successful representation, not as a status that can be inferred after a truncated transfer (Fielding et al., 2022). RFC 3986 §5.2.4 defines dot-segment removal, so accepting `.` or `..` as a repository path component would make URL interpolation ambiguous even when a superficial single-slash shape check passes (Berners-Lee et al., 2005). NIST SP 800-53 Rev. 5 RA-5 and SA-12 require that vulnerability and supply-chain evidence be obtained, not assumed absent (National Institute of Standards and Technology, 2020). SLSA v1.0 likewise treats missing provenance as unverified rather than passing (SLSA, 2023). An HTTP `403` or `404` is therefore unavailable evidence, not a clean skip.

## Identity and authority

The dependency-review job checks out the pull request's explicit head repository and immutable head SHA with persisted credentials disabled. The API comparison independently binds the event's exact base and head revisions. Before URL construction, the workflow rejects named revisions, malformed object IDs, repository strings that are not exactly `owner/name`, and `.`/`..` path components. These checks are executable regressions: invalid identity must fail before the fake HTTP client is reached, while the `ContextualWisdomLab/.github` product repository must still reach an otherwise successful compare.

The job retains `contents: read` and `pull-requests: read`; it receives no write, OIDC, model, release, package, or deployment authority. Checks, status contexts, review submissions, and merge authorization remain separate evidence classes. OSV, Trivy, CodeQL, Semgrep, Secret Scan, Scorecard, and Dependabot are complementary controls and are not semantic substitutes for dependency review.

## Failure classification and remediation

- Invalid evidence identity (named/non-hex revision, non-`owner/name` repository value, or a `.`/`..` component): fail before curl. Correct the event identity; do not retry a moving or path-normalized target.
- Transport exit `0` plus HTTP `200`: proceed to the pinned dependency-review action.
- Any other transport/status result: fail the job and retain exact repository/base/head/status and transport-exit evidence. An HTTP `200` emitted by a failed or partial transfer is unavailable evidence.
- Public repository failure: verify dependency graph and security configuration, organization policy, token read access, and GitHub service health.
- Private or internal exception: require a separately reviewed organization policy with explicit entitlement evidence and compensating controls. Never infer `not-applicable` from an unavailable response.

Retries are operator-initiated only after the capability or service condition changes. Do not rerun unchanged evidence repeatedly and do not convert an unavailable endpoint into a green skip.

## Acceptance and rollback

Acceptance requires the permanent queue contract to reject the former `supported=false` path, require bounded probing and discarded bodies, require exact-head checkout, reject named revisions and malformed repository identities before transport, and prove that only transport success plus HTTP `200` reaches the action. Exact-head CI/security evidence, current review, protected integration, and a real protected-main consumer run remain required.

Rollback requires an independently reviewed revert and fresh exact-head evidence. A rollback must not restore the `403`/`404` success path, accept moving/nonnormalized comparison identities, or print an API response body.

## References

Berners-Lee, T., Fielding, R., & Masinter, L. (2005). *Uniform Resource Identifier (URI): Generic syntax* (RFC 3986). Internet Engineering Task Force. https://doi.org/10.17487/RFC3986

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics* (RFC 9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

GitHub. (n.d.). *Dependency review*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review

GitHub. (n.d.). *REST API endpoints for dependency review*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/rest/dependency-graph/dependency-review

GitHub. (n.d.). *Dependency graph*. GitHub Docs. Retrieved September 2, 2026, from https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-graph

National Institute of Standards and Technology. (2020). *Security and privacy controls for information systems and organizations* (NIST SP 800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

SLSA. (2023). *SLSA v1.0: Supply-chain Levels for Software Artifacts*. Open Source Security Foundation. https://slsa.dev/spec/v1.0/
