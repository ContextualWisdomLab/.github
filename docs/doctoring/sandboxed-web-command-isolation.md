# Sandboxed web command isolation

`sandboxed_web_e2e.py` requires Linux `bubblewrap` (`bwrap`) by default. Each
backend, frontend, and E2E command runs with a read-only runtime root and a
single writable mount at `/workspace`; the copied repository and temporary
homes are mapped there. The host filesystem is therefore not reachable through
absolute paths or `..` traversal.

Before wrapping a command, the helper resolves its executable and rejects paths
outside the read-only system roots mounted by bubblewrap. A tool installed in a
host-only location must be installed into one of those roots or the run exits
before any service starts.

Use `--isolation disabled` only for trusted local debugging. The result marker
records the requested mode and resolved backend so CI evidence cannot be
mistaken for an OS-isolated run. If required isolation is unavailable, the
command exits with code `126` before starting any service.

Readiness polling remains loopback-only and does not follow redirects. Invalid
readiness URLs are reported as a coded readiness failure (`125`) rather than an
uncaught traceback. The network declaration is evidence metadata; callers that
need stronger network policy must run this helper inside a network-restricted
runner or container.

## References

MITRE. (2026). *CWE-918: Server-side request forgery (SSRF)*.
https://cwe.mitre.org/data/definitions/918.html
