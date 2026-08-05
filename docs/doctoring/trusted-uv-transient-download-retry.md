# Trusted uv transient download retry boundary

## Decision

The central coverage materializer downloads one checksum-pinned uv archive from one literal Astral HTTPS URL. It performs at most **three total attempts**, separated by deterministic delays of one and two seconds, only for this closed availability set:

- HTTP `408`, `425`, `429`, `500`, `502`, `503`, and `504`;
- temporary DNS resolution reported as `EAI_AGAIN`;
- `TimeoutError`; and
- connection aborted, refused, or reset, plus explicit host or network down, reset, unreachable, or timed-out operating-system errors.

The fixed `GET` is safe and idempotent, so a bounded retry does not mutate remote or repository state. Each attempt repeats the same literal URL and exact timeout. The retry loop does not follow redirects, enable proxies, change the release URL, use repository-controlled headers, or accept an unverified payload.

## Fail-closed exclusions

The following conditions are never retried:

- every HTTP response outside the exact closed set, including authorization, not-found, and unsupported-method failures;
- certificate verification or any other TLS failure;
- permanent DNS failure;
- a malformed or non-exception `URLError.reason`;
- local permission failures and every unclassified `OSError`;
- redirect attempts or a final origin or port outside the fixed Astral HTTPS origin;
- an oversized archive;
- SHA-256 mismatch;
- malformed archive members, incorrect executable size or type, unsupported runner architecture, or unexpected uv version; and
- offline export, exact-pin grammar, Git-tree, TOML, or workspace-boundary failures.

A response body belongs to one attempt only. Partial bytes read before a transient failure are discarded before the next attempt. Retry exhaustion reports only a bounded HTTP status, transport errno, or exception class and the attempt count. It never includes exception text, URLs, response bodies, headers, credentials, or URL-derived user information.

## Incident evidence

Central OpenCode coverage run `31002427460` for `ContextualWisdomLab/newsdom-api#524` reached the exact trusted-uv materialization stage and failed with `trusted uv archive download failed: HTTPError`. The source PR changed only `AGENTS.md`; all repository-local checks were successful. A later workflow in the same operating window downloaded the pinned uv release successfully, supporting a bounded transient-retry response rather than weakening the immutable bootstrap or bypassing coverage.

The same failure class later blocked exact-head OpenCode coverage for `ContextualWisdomLab/pg-llm-batch#53` in central workflow run `31022108085`. Repository-local CI, security, and SAST checks passed on that exact product head, while trusted uv archive materialization failed before PR-controlled tests ran.

## Verification contract

Permanent tests require:

- every HTTP status in the exact closed set receives one bounded retry;
- representative permanent HTTP responses fail after one attempt and no sleep;
- temporary DNS, timeout, and connection-reset failures retry;
- certificate verification, permanent DNS, malformed transport reasons, and unclassified local errors fail after one attempt and no sleep;
- persistent transient failures stop after exactly three attempts and delays of one and two seconds;
- every attempt reuses the literal trusted URL and exact timeout;
- partial bytes from a failed response are absent from the next attempt; and
- the no-proxy opener, redirect rejection, final-origin validation, repeated bounded reads, maximum size, checksum, archive member, executable version, Python compatibility, offline export, full SHA-256 grammar, 100% statement and branch coverage, and production docstrings remain unchanged.

A permanent documentation contract rejects broader legacy wording such as all `URLError` or `OSError` failures and generic `5xx` retries.

## MSA and operational boundary

This retry belongs to the organization-owned coverage control plane because every leaf repository consumes the same trusted bootstrap. Leaf repositories such as pg-llm-batch, NewsDOM, and naruon must not duplicate a downloader or weaken their review gates. If all three attempts fail, the current-head review remains fail-closed and publishes bounded evidence; no approval or merge is synthesized.

## Rollback

Rollback removes the retry constants and loop while retaining every immutable-source, no-proxy, no-redirect, bounded-read, checksum, archive, executable-version, and offline-export control. Operators may also set the delay tuple to empty in a reviewed change to restore one attempt. Increasing attempts, delays, or the closed classifier requires a separate availability, security, and runner-budget review.

## References

Fielding, R. T., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC 9110). RFC Editor. https://doi.org/10.17487/RFC9110

Nottingham, M., & Fielding, R. (2012). *Additional HTTP status codes* (RFC 6585). RFC Editor. https://doi.org/10.17487/RFC6585

Python Software Foundation. (2026). *urllib.error—Exception classes raised by urllib.request*. Python 3.14 documentation. https://docs.python.org/3/library/urllib.error.html

Thomson, M., Nottingham, M., & Tarreau, W. (2018). *Using early data in HTTP* (RFC 8470). RFC Editor. https://doi.org/10.17487/RFC8470
