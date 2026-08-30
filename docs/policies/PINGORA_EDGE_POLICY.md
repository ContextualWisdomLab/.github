# Cloudflare Pingora Edge Runtime Policy

## Binding rule

ContextualWisdomLab production and test edge runtimes use **Cloudflare Pingora**.
Active Nginx containers, packages, commands, configuration files, Kubernetes
Nginx ingress annotations/classes, and host-service units are prohibited.

This is a runtime boundary, not a vocabulary ban. Documentation, byte-validated
raster evidence beneath a documentation directory, license notices, dedicated
source fixtures under `tests/fixtures/`, the scanner source itself, and migration
histories may name Nginx. Executable integration and end-to-end test helpers remain
runtime candidates. Pull requests that modify a runtime candidate are evaluated
against the final exact head file, so deleting a legacy artifact is allowed while
preserving it or introducing a new one fails closed.

## Why this is not a search-and-replace

Pingora is a programmable Rust framework rather than an Nginx configuration
interpreter. The organization therefore maintains reusable, versioned Pingora
static-serving and proxy artifacts and gives product repositories only declarative
route/site contracts. Product repositories do not fork proxy internals.

## Required migration contract

1. Inventory the current listener, host/path matching, TLS ownership, static root,
   upstream protocol, WebSocket/streaming behavior, body/timeout limits, headers,
   health probes, metrics, and rollback path.
2. Reproduce those behaviors with the approved Pingora artifact and a versioned
   route/site manifest.
3. Add behavior-level tests before deleting the old runtime artifact.
4. Pin Pingora to an exact release at or above `0.8.0`; the shared baseline is
   `0.8.1`. Do not use the experimental Pingora cache integration in the initial
   migration.
5. Preserve certificate data and rollback evidence, but never keep a runnable
   Nginx fallback after cutover. Rollback means redeploying the prior application
   release behind Pingora, not reintroducing Nginx.
6. Treat PHP/FastCGI workloads as application-runtime migrations: place an
   HTTP-capable PHP application server or a reviewed FastCGI adapter behind
   Pingora before cutover. Pingora must remain the public HTTP/TLS edge.

## Ownership

- `.github` owns the binding policy, scanner, shared contracts, and required gate.
- `linux-cluster-ops` owns environment-specific listeners, certificates, routes,
  service units, backups, rollout, and host cutover.
- Each product owns its static build or upstream application behavior and tests.
- Keyverse remains the identity authority; an edge runtime never becomes the
  identity system of record.

## Enforcement and evidence

The organization-required `required-workflow-bootstrap` job runs trusted
base-branch scanner code at the immutable required-workflow SHA. It reads bounded
changed-file metadata and final UTF-8 content through GitHub's REST API. It does
not check out or execute pull-request content and receives only read permissions.
Malformed, truncated, unexpected binary, symlink, oversized, or unavailable
evidence fails closed. Supported documentation raster evidence is fetched and
validated by file signature before it is excluded from the text scanner.

## Exception process

There is no standing Nginx exception. A temporary exception requires a public ADR
with an owner, exact affected asset, buyer impact, security controls, removal date,
and an approved Pingora migration PR. The central scanner remains unchanged; the
exception is implemented by completing the migration before merge.
