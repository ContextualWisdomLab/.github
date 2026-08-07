# Dependency-review support probe fail-closed contract

## Incident

The required central `Security Scan` workflow probes GitHub's dependency-review compare endpoint before invoking `actions/dependency-review-action`. The probe already treated every HTTP status other than 200 as unavailable evidence. However, the shell command substitution appended `|| true`, so a transport-level `curl` failure could be converted into shell success. Because `curl --write-out '%{http_code}'` can emit an HTTP status even when the transfer itself later fails, an output of `200` paired with a nonzero curl exit status could incorrectly set `supported=true`.

This is an evidence-integrity defect rather than a dependency vulnerability. A required security gate must not claim the dependency-review prerequisite is available unless both the transport command and the API status prove success.

## Decision

The support probe now has two independent fail-closed conditions:

1. `curl` must exit successfully under the existing ten-second connection timeout and thirty-second total timeout; and
2. the returned status text must be exactly `200` for the exact pull-request base/head comparison.

The workflow discards the untrusted response body and writes `supported=true` only after both conditions pass. Timeout, partial transfer, connection failure, TLS failure, malformed or empty status output, HTTP 403/404, and every other non-200 response terminate the job. The dependency-review action, its immutable pin, its severity threshold, workflow permissions, API endpoint, API-version header, and credential identity are unchanged.

## Test-first evidence

`tests/test_dependency_review_support_probe.py` executes the exact shell body extracted from `.github/workflows/security-scan.yml` with an injected fake `curl`. The regression makes `curl` print HTTP `200` and then exit with code 18, representing a partial-transfer failure. The accepted contract is that the shell step exits nonzero, emits the existing fail-closed diagnostic, and never writes `supported=true` to `GITHUB_OUTPUT`.

The regression was committed before the workflow repair so the defect remained observable independently of the implementation change.

## Operational interpretation

A failed support probe means dependency-review assurance is unavailable for that exact base/head pair. It is not permission to skip the dependency-review job and it must not be reclassified as success because another scanner passed. Retry after an infrastructure or GitHub service failure; remediate repository feature or authorization configuration for persistent 403/404 responses. Only a successful probe followed by the required dependency-review action can satisfy this part of the central supply-chain gate.

## Rollback

Rollback requires an independently reviewed replacement that preserves both transport-success and exact-HTTP-200 evidence. Restoring `|| true`, treating a nonzero curl exit as advisory, or allowing 403/404 to produce a successful skip would reintroduce the fail-open condition and is not an acceptable rollback.

## APA 7th references

GitHub. (2026). *REST API endpoints for dependency review*. GitHub Docs. Retrieved August 7, 2026, from https://docs.github.com/en/rest/dependency-graph/dependency-review

The curl project. (2026). *curl: How to use*. Retrieved August 7, 2026, from https://curl.se/docs/manpage.html

The curl project. (2026). *libcurl error codes*. Retrieved August 7, 2026, from https://curl.se/libcurl/c/libcurl-errors.html
