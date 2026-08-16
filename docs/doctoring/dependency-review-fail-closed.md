# Dependency review fail-closed operations

Status: `active_pr` until the matching workflow and regression contract are present on protected `main`; thereafter `implemented_on_protected_main`.

## Decision

Dependency review is a hard supply-chain gate. The central workflow accepts only HTTP `200` from GitHub's exact `BASE_SHA...HEAD_SHA` comparison before invoking the immutably pinned dependency-review action. A `403`, `404`, `400`, `500`, `503`, empty or malformed status, curl `000` sentinel, timeout, transport failure, truncated exchange, or other unexpected outcome is unavailable evidence and fails closed.

The support probe has a 10-second connection limit and 30-second total limit. It preserves curl's transport exit code separately from the bounded HTTP status and requires transport exit `0` plus exact HTTP `200`. It discards the response body and logs only repository identity, allowlisted visibility (`public`, `private`, `internal`, or `unknown`), exact base/head revisions, the normalized HTTP status, and the numeric transport exit. Credentials, response bodies, raw untrusted visibility strings, named refs, and raw invalid repository paths are never diagnostic output. After a successful probe the pinned action is not independently skippable.

Before any compare request, the probe requires an `owner/name` repository identity and exact Git object IDs: 40 hexadecimal characters for SHA-1 or 64 hexadecimal characters for SHA-256 (Chacon & Straub, 2014; National Institute of Standards and Technology, 2015). GitHub's compare API resolves named revisions such as `main` to the current HEAD of that name (GitHub, n.d.). That moving target is not the pull-request head and is unavailable evidence. Rejecting it before interpolation also prevents path injection into `/repos/{owner}/{repo}/dependency-graph/compare/{basehead}` (MITRE, 2026).

RFC 9110 §15.3.1 defines `200` as a completed successful representation, not as a status that can be inferred after a truncated transfer (Fielding et al., 2022). curl's `%{http_code}` write-out is the numeric status from the last retrieved transfer; when no HTTP status was received it emits `000` (Stenberg, n.d.). That sentinel is unavailable evidence, not an HTTP status. NIST SP 800-53 Rev. 5 RA-5 and SA-12 require that vulnerability and supply-chain evidence be obtained, not assumed absent (National Institute of Standards and Technology, 2020). SLSA v1.0 likewise treats missing provenance as unverified rather than passing (SLSA, 2023). An HTTP `403` or `404` is therefore unavailable evidence, not a clean skip. GitHub documents `403` as the private-repository response when GitHub Advanced Security is not enabled, or when the comparison targets a fork (GitHub, n.d.). Record the allowlisted visibility and exact revisions, then verify dependency-graph or Advanced Security configuration. Do not infer `not-applicable` from `403`.

## Identity and authority

The dependency-review job checks out the pull request's explicit head repository and immutable head SHA with persisted credentials disabled. The API comparison independently binds the event's exact base and head Git object IDs after those values pass the hexadecimal length check. The job retains `contents: read` and `pull-requests: read`; it receives no write, OIDC, model, release, package, or deployment authority.

Checks, status contexts, review submissions, and merge authorization remain separate evidence classes. OSV, Trivy, CodeQL, Semgrep, Secret Scan, Scorecard, and Dependabot are complementary controls and are not semantic substitutes for dependency review.

## Failure classification and remediation

- Identity rejected (named ref, empty or non-hex revision, or non-`owner/name` repository): fail the job before curl. Use the pull-request event's exact hexadecimal SHAs and `owner/name`, then rerun.
- Transport exit `0` plus HTTP `200`: proceed to the pinned dependency-review action.
- Any other result: fail the job and retain exact repository, allowlisted visibility, base/head, status, and transport-exit evidence. An HTTP `200` emitted by a failed or partial transfer is unavailable evidence. curl `000` is recorded as `unavailable`. Do not infer a root cause from HTTP `403` or `404`.
- Public repository failure: verify dependency graph and security configuration, organization policy, token read access, and GitHub service health.
- HTTP `403` on a private or internal repository: verify whether GitHub Advanced Security / dependency review is entitled for that repository. Keep the job failed until a separately reviewed organization exception with compensating controls exists. Never infer `not-applicable` from an unavailable response.

Retries are operator-initiated only after the capability or service condition changes. Do not rerun unchanged evidence repeatedly and do not convert an unavailable endpoint into a green skip.

## Known canary

ContextualWisdomLab/EgressWeave#66, Security Scan run `31108241013`, job `92638903658`, compared `10d0c51daf2ad278d66f43be479df8cf6b08ba6d...c038a9509d1a8eae8561cc9081e67e12bd373d42` and received HTTP `403`. The required workflow printed the skip warning, omitted `actions/dependency-review-action`, and still concluded success. Downstream tracking: ContextualWisdomLab/EgressWeave#76. Keep ContextualWisdomLab/.github#810 open until a protected-main public consumer run proves a non-200 or failed-transfer comparison cannot green this job.

## Acceptance and rollback

Acceptance requires the permanent queue contract to reject the former `supported=false` path, require bounded probing and discarded bodies, require exact-head checkout, reject named refs and non-`owner/name` repository values before any compare request, and prove that only `200` reaches the action. Exact-head CI/security evidence, current review, protected integration, and a real protected-main consumer run remain required.

Rollback requires an independently reviewed revert and fresh exact-head evidence. A rollback must not restore the `403`/`404` success path, accept named revisions as compare evidence, or print an API response body.

## References

Chacon, S., & Straub, B. (2014). *Pro Git* (2nd ed.). Apress.
https://git-scm.com/book/en/v2/Git-Internals-Git-Objects

Fielding, R., Nottingham, M., & Reschke, J. (Eds.). (2022). *HTTP semantics*
(RFC 9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

GitHub. (n.d.). *Dependency review*. GitHub Docs. Retrieved August 9, 2026, from https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review

GitHub. (n.d.). *REST API endpoints for dependency review*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/rest/dependency-graph/dependency-review

GitHub. (n.d.). *Dependency graph*. GitHub Docs. Retrieved August 9, 2026, from https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-graph

GitHub. (n.d.). *Webhook events and payloads*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/webhooks/webhook-events-and-payloads#repository

MITRE. (2026). *CWE-20: Improper input validation*.
https://cwe.mitre.org/data/definitions/20.html

National Institute of Standards and Technology. (2015). *Secure hash
standard (SHS)* (FIPS 180-4). https://doi.org/10.6028/NIST.FIPS.180-4

National Institute of Standards and Technology. (2020). *Security and
privacy controls for information systems and organizations* (NIST SP
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

SLSA. (2023). *SLSA v1.0: Supply-chain Levels for Software Artifacts*.
Open Source Security Foundation. https://slsa.dev/spec/v1.0/

Stenberg, D. (n.d.). *curl -- write out variables*. curl. Retrieved August 16, 2026, from https://curl.se/docs/manpage.html
