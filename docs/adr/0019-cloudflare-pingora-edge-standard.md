# ADR-0019: Standardize the CWL edge runtime on Cloudflare Pingora

- **Status:** Accepted
- **Date:** 2026-08-18
- **Decision owners:** ContextualWisdomLab platform and product maintainers

## Context

CWL repositories currently carry several unrelated Nginx images, configuration
files, ingress annotations, service scripts, and host runbooks. The duplication
creates drift in headers, TLS, timeouts, WebSocket handling, non-root operation,
metrics, and security patching. It also makes every product repository an edge
runtime maintainer.

Cloudflare Pingora supplies an Apache-2.0, Rust-based framework for HTTP/1 and
HTTP/2 proxying, TLS, gRPC/WebSocket forwarding, graceful reload, failover, and
observability. It is a framework, not a drop-in parser for Nginx configuration,
so a governed shared implementation is required.

## Decision

1. Pingora is the only approved CWL public HTTP reverse-proxy, load-balancer, and
   static edge runtime.
2. The shared implementation pins Pingora `0.8.1`; updates use a reviewed version
   bump, security advisory review, compatibility tests, and exact-current-head CI.
3. Product repositories consume versioned static/proxy artifacts and declarative
   contracts. Environment deployment remains in `linux-cluster-ops`.
4. The organization required workflow rejects active Nginx runtime artifacts in
   changed final files without executing pull-request code.
5. Initial migration does not use Pingora's experimental cache integration.
6. PHP workloads move to an HTTP application server or reviewed FastCGI adapter
   behind Pingora before the public listener changes.

## Consequences

### Positive

- One memory-safe, programmable edge framework and patch stream.
- Reusable security headers, request limits, metrics, graceful shutdown, and
  connection-management behavior.
- Product repositories stop maintaining bespoke proxy configuration.
- Exact-head organization enforcement prevents regression.

### Costs and risks

- Nginx configuration cannot be translated mechanically; behavior must be tested.
- The organization owns Rust proxy code and its release lifecycle.
- TLS/SNI, FastCGI, caching, and advanced ingress features need explicit modules.
- A faulty shared artifact has broad blast radius, so canary, digest pinning,
  rollback, and independent review are mandatory.

## Alternatives rejected

- **Keep Nginx with templates:** preserves configuration drift and C-runtime risk.
- **Traefik as the universal gateway:** useful off-the-shelf controller, but does
  not meet the user-mandated Pingora standard and creates a second edge runtime.
- **Per-repository Pingora binaries:** duplicates security logic and fragments the
  upgrade path.
- **Immediate host replacement without behavior tests:** creates unacceptable
  outage and certificate risk.

## Validation

The policy scanner has 100% production statement and branch coverage, bounded
GitHub API evidence, path/control escaping, pagination limits, exact-head content
inspection, and fail-closed malformed-evidence tests. Product migrations require
site/proxy behavior tests and deployment-specific smoke tests before cutover.
