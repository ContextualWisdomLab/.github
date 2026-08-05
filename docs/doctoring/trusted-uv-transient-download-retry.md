# Trusted uv transient download retry boundary

## Decision

The central coverage materializer downloads one checksum-pinned uv archive from one literal Astral HTTPS URL. It now performs at most **three total attempts**, separated by deterministic delays of one and two seconds, only for bounded transport failures:

- connection-level `urllib.error.URLError` or `OSError` failures;
- HTTP 408, 429, 500, 502, 503, and 504 responses.

The fixed `GET` is safe and idempotent, so a bounded retry does not mutate remote or repository state. The retry loop does not follow redirects, enable proxies, change the release URL, use repository-controlled headers, or accept an unverified payload.

## Fail-closed exclusions

The following conditions are never retried:

- permanent HTTP failures such as 400, 401, 403, or 404;
- redirect attempts or a final origin/port outside the fixed Astral HTTPS origin;
- an oversized archive;
- SHA-256 mismatch;
- malformed archive members, incorrect executable size or type, unsupported runner architecture, or unexpected uv version;
- offline export, exact-pin grammar, Git-tree, TOML, or workspace-boundary failures.

Retry exhaustion reports only the bounded exception class or numeric HTTP status and the attempt count. It does not include URLs, response bodies, headers, credentials, or arbitrary exception text.

## Incident evidence

Central OpenCode coverage run `31002427460` for `ContextualWisdomLab/newsdom-api#524` reached the exact trusted-uv materialization stage and failed with `trusted uv archive download failed: HTTPError`. The source PR changed only `AGENTS.md`; all repository-local checks were successful. A later workflow in the same operating window downloaded the pinned uv release successfully, supporting a bounded transient-retry response rather than weakening the immutable bootstrap or bypassing coverage.

## Verification contract

Permanent tests require:

- a transient HTTP 503 followed by a valid response succeeds after one one-second delay;
- a connection-level `URLError` receives the same bounded retry;
- three persistent transient failures stop after exactly three attempts and delays of one and two seconds;
- an HTTP 404 fails immediately without sleeping;
- the literal URL, no-proxy opener, redirect rejection, final-origin validation, repeated bounded reads, maximum size, checksum, archive member, executable version, Python compatibility, offline export, full SHA-256 grammar, 100% statement/branch coverage, and production docstrings remain unchanged.

## MSA and operational boundary

This retry belongs to the organization-owned coverage control plane because every leaf repository consumes the same trusted bootstrap. Leaf repositories such as NewsDOM and naruon must not duplicate a downloader or weaken their review gates. If all three attempts fail, the current-head review remains fail-closed and publishes actionable coverage evidence; no approval or merge is synthesized.

## Rollback

Rollback removes the retry constants and loop while retaining all immutable-source, no-proxy, no-redirect, bounded-read, checksum, archive, executable-version, and offline-export controls. Operators may also set the delay tuple to empty in a reviewed change to restore one attempt. Increasing attempts or delays requires a separate availability and runner-budget review.

## References

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://doi.org/10.17487/RFC9110

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes* (RFC 6585). RFC Editor. https://doi.org/10.17487/RFC6585

Python Software Foundation. (2026). *urllib.error—Exception classes raised by urllib.request*. Python 3.14 documentation. https://docs.python.org/3/library/urllib.error.html

## Closed retry classification

The retryable HTTP set is exactly `408`, `425`, `429`, `500`, `502`, `503`, and
`504`. Transport retries are limited to temporary DNS (`EAI_AGAIN`), timeout,
connection reset/refused/aborted, and explicit host or network unavailable
errors. Certificate verification, other TLS failures, permanent DNS, malformed
`URLError.reason`, local permission errors, and every unclassified `OSError`
fail after one attempt.

Each attempt repeats the same literal Astral URL and exact timeout. A failed
response body is scoped to that attempt, so partial bytes are discarded before
retry. Diagnostics expose only a bounded HTTP status, transport errno, or
exception class and never exception text, URL-derived credentials, headers, or
body content.
