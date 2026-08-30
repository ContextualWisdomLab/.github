# Sandboxed web command isolation

`sandboxed_web_e2e.py` requires Linux `bubblewrap` (`bwrap`) by default. Each
backend, frontend, and E2E command runs with a fresh writable `tmpfs` root and
`/tmp`, plus one writable copied-repository bind at `/workspace`; the copied
repository and temporary homes are mapped there. Host runtime roots and the
minimal `/etc` identity, DNS, and time files are mounted read-only, so the host
filesystem is not reachable through absolute paths or `..` traversal.

Before wrapping a command, the helper resolves its executable and rejects paths
outside the read-only system roots mounted by bubblewrap. An executable that
cannot be resolved at all is rejected the same way, rather than passed through
unvalidated. A tool installed in a host-only location must be installed into
one of those roots or the run exits with code `126` before any service starts;
the result marker records that code and the selected backend.

Use `--isolation disabled` only for trusted local debugging. The result marker
records the requested mode and resolved backend so CI evidence cannot be
mistaken for an OS-isolated run. If required isolation is unavailable, the
command exits with code `126` before starting any service. A `bwrap` binary on
PATH is not, by itself, taken as proof isolation works: a bounded capability
probe exercises the same essential namespace and mount operations
`isolated_command` depends on before any service starts, so a restricted host
that can locate `bwrap` but cannot create the required namespaces is also
classified as unavailable (`126`) instead of failing later as a confusing
readiness or test error.

Readiness polling remains loopback-only and does not follow redirects. Invalid
readiness URLs are reported as a coded readiness failure (`125`) rather than an
uncaught traceback. The network declaration is evidence metadata; callers that
need stronger network policy must run this helper inside a network-restricted
runner or container.

## References

MITRE. (2026). *CWE-918: Server-side request forgery (SSRF)*.
https://cwe.mitre.org/data/definitions/918.html
