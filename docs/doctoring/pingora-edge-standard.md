# Doctoring record: Cloudflare Pingora edge standard

## Decision trace

CWL standardizes public HTTP edge behavior on Cloudflare Pingora and prohibits
active Nginx runtime artifacts. Pingora is treated as a programmable framework;
shared binaries and declarative contracts prevent each product from becoming a
proxy implementation owner.

The minimum allowed Pingora line is `0.8.x`. Versions through `0.7.0` were affected
by a critical HTTP request-smuggling flaw caused by ambiguous HTTP/1 framing;
`0.8.0` patched it. The selected `0.8.1` release additionally bounded default
HTTP/2 server limits and updated security-sensitive Rustls development
dependencies. The initial CWL implementation avoids experimental cache APIs.

## Standards and controls

- HTTP parsing and proxy behavior must follow the patched Pingora framing model
  and RFC 9112 semantics referenced by the upstream advisory.
- The shared artifact is Apache-2.0 compatible with CWL permissive-license policy.
- Required-workflow code is bound to its immutable central SHA and never executes
  pull-request content.
- Runtime evidence is bounded to one-megabyte regular-file bytes, with UTF-8
  decoding for runtime candidates and supported raster-format validation for
  documentation images; the maximum is 3,000 changed files and missing or
  malformed evidence fails closed.
- Exact-head product tests cover host/path routing, SPA fallback, security headers,
  WebSocket/streaming, body limits, health, metrics, TLS, and graceful shutdown as
  applicable.

## APA 7th references

Cloudflare, Inc. (2026, June 4). *Pingora 0.8.1* [Software release]. GitHub.
https://github.com/cloudflare/pingora/releases/tag/0.8.1

Cloudflare, Inc. (2026, March 5). *HTTP request smuggling via HTTP/1.0 and
Transfer-Encoding misparsing* (GHSA-hj7x-879w-vrp7) [Security advisory]. GitHub.
https://github.com/cloudflare/pingora/security/advisories/GHSA-hj7x-879w-vrp7

Cloudflare, Inc. (n.d.). *Pingora* [Computer software]. GitHub. Retrieved August
18, 2026, from https://github.com/cloudflare/pingora

Cloudflare, Inc. (n.d.). *Pingora user guide*. GitHub. Retrieved August 18, 2026,
from https://github.com/cloudflare/pingora/tree/main/docs/user_guide
