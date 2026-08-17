# Dependency review fail-closed operations

Status: `active_pr` until the matching workflow and regression contract are present on protected `main`; thereafter `implemented_on_protected_main`.

## Decision

Dependency review is a hard supply-chain gate. The central workflow accepts only HTTP `200` from GitHub's exact `BASE_SHA...HEAD_SHA` comparison, with curl transport exit `0`, before invoking the immutably pinned dependency-review action. A `403`, `404`, empty or malformed status, timeout, transport failure, truncated exchange, or other unexpected outcome is unavailable evidence and fails closed.

The support probe validates identity before any network call. Both revisions must be 40- or 64-character hex object ids; named refs are not evidence. The repository must be canonical `owner/name` without `.` or `..` path segments (the special `.github` repository name remains legal). Malformed identity fails closed with HTTP `unavailable` and curl exit `uncalled` and does not echo the raw values.

The probe has a 10-second connection limit and 30-second total limit. It preserves curl's transport exit code separately from the bounded HTTP status and requires transport exit `0` plus exact HTTP `200`. Curl's `000` sentinel is unavailable evidence. It discards the response body and logs only repository identity, allowlisted visibility (`public`, `private`, `internal`, or `unknown`), exact base/head revisions, the normalized HTTP status, and the numeric transport exit. Credentials, response bodies, and raw untrusted visibility strings are never diagnostic output. After a successful probe the pinned action is not independently skippable.

RFC 9110 §15.3.1 defines `200` as a completed successful representation, not as a status that can be inferred after a truncated transfer (Fielding et al., 2022). NIST SP 800-53 Rev. 5 RA-5 and SA-12 require that vulnerability and supply-chain evidence be obtained, not assumed absent (National Institute of Standards and Technology, 2020). SLSA v1.0 likewise treats missing provenance as unverified rather than passing (SLSA, 2023). An HTTP `403` or `404` is therefore unavailable evidence, not a clean skip.

## Identity and authority

The dependency-review job checks out the pull request's explicit head repository and immutable head SHA with persisted credentials disabled. The API comparison independently binds the event's exact base and head revisions. The job retains `contents: read` and `pull-requests: read`; it receives no write, OIDC, model, release, package, or deployment authority.

Checks, status contexts, review submissions, and merge authorization remain separate evidence classes. OSV, Trivy, CodeQL, Semgrep, Secret Scan, Scorecard, and Dependabot are complementary controls and are not semantic substitutes for dependency review.

## Failure classification and remediation

- Transport exit `0` plus HTTP `200` after validated identity: proceed to the pinned dependency-review action.
- Malformed revision or repository: fail before curl with HTTP `unavailable` and curl exit `uncalled`. Do not echo the raw identity.
- Any other result: fail the job and retain exact repository, allowlisted visibility, base/head, status, and transport-exit evidence. An HTTP `200` emitted by a failed or partial transfer, and curl's `000` sentinel, are unavailable evidence. Do not infer a root cause from HTTP `403` or `404`.
- Public repository failure: verify dependency graph and security configuration, organization policy, token read access, and GitHub service health.
- Private or internal exception: require a separately reviewed organization policy with explicit entitlement evidence and compensating controls. Never infer `not-applicable` from an unavailable response.

Retries are operator-initiated only after the capability or service condition changes. Do not rerun unchanged evidence repeatedly and do not convert an unavailable endpoint into a green skip.

## Acceptance and rollback

Acceptance requires the permanent queue contract to reject the former `supported=false` path, require bounded probing and discarded bodies, require exact-head checkout, and prove that only `200` with curl exit `0` reaches the action. Exact-head CI/security evidence, current review, protected integration, and a real protected-main consumer run remain required.

Do not close ContextualWisdomLab/.github#810 until a protected-main public-repository consumer run (for example ContextualWisdomLab/EgressWeave) proves a non-200 or failed-transfer comparison cannot produce a green Dependency Review gate.

Rollback requires an independently reviewed revert and fresh exact-head evidence. A rollback must not restore the `403`/`404` success path or print an API response body.

## References

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

GitHub. (n.d.). *Dependency review*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review

GitHub. (n.d.). *REST API endpoints for dependency review*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/rest/dependency-graph/dependency-review

GitHub. (n.d.). *Dependency graph*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-graph

GitHub. (n.d.). *Webhook events and payloads*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/webhooks/webhook-events-and-payloads#repository

National Institute of Standards and Technology. (2020). *Security and
privacy controls for information systems and organizations* (NIST SP
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

SLSA. (2023). *SLSA v1.0: Supply-chain Levels for Software Artifacts*.
Open Source Security Foundation. https://slsa.dev/spec/v1.0/
