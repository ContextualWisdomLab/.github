# Sandboxed web command isolation

`sandboxed_web_e2e.py` requires Linux `bubblewrap` (`bwrap`) by default. Each
backend, frontend, and E2E command runs with a fresh writable `tmpfs` root and
`/tmp`, plus one writable copied-repository bind at `/workspace`; the copied
repository and temporary homes are mapped there. Host runtime roots and the
minimal `/etc` identity, DNS, and time files are mounted read-only, so the host
filesystem is not reachable through absolute paths or `..` traversal.

Before wrapping a command, the helper resolves its executable and rejects paths
outside the read-only system roots mounted by bubblewrap. A tool installed in a
host-only location must be installed into one of those roots or the run exits
with code `126` before any service starts; the result marker records that code
and the selected backend. An executable that cannot be resolved on `PATH` at
all is rejected the same way — it is never handed unvalidated to bubblewrap or
the shell to resolve on its own.

A `bwrap` binary discovered on `PATH` is not by itself proof that isolation
works: a restricted host (unprivileged user namespaces disabled, or a
seccomp-restricted CI runner) can have the binary present yet unable to create
the requested namespaces. Before starting either service, `isolation_backend`
runs a bounded, cheap capability preflight — the same minimal namespace and
mount shape `isolated_command` uses (new PID namespace, tmpfs root, the
standard read-only binds, `/proc`, `/dev`, a tmpfs `/tmp`) around a trivial
no-op executable. A non-zero exit, or a failure to even launch the probe, is
classified as isolation-unavailable and exits with code `126`, the same as a
missing `bwrap` binary, instead of surfacing later as a confusing readiness or
test failure.

Use `--isolation disabled` only for trusted local debugging. The result marker
records the requested mode and resolved backend so CI evidence cannot be
mistaken for an OS-isolated run. If required isolation is unavailable, the
command exits with code `126` before starting any service.

The workspace copy this helper and `sandboxed_verify.py` share
(`sandboxed_verify.copy_workspace`) preserves symlinks rather than
dereferencing them. Under `--isolation required`, a symlink whose absolute
target is not one of the explicitly bound paths already dangles safely
(`ENOENT`) inside bubblewrap's `tmpfs` root — verified empirically against
this code path. That containment does not extend to two paths that share the
same copy step: `--isolation disabled` (documented as trusted local debugging
only, but the copy itself makes no such distinction) runs the wrapped commands
directly on the host with no OS sandboxing at all, and `sandboxed_verify.py`'s
own verification command never runs inside bubblewrap in the first place. In
both, a repository-supplied symlink whose target is an absolute host path, or
a relative path with enough `..` segments to exit the copy, remains a live
symlink that a command following it can use to read or write host files
outside the intended workspace. Every symlink under the copy is therefore
resolved and checked against the workspace root immediately after
`shutil.copytree`, in `copy_workspace` itself so both callers get the same
protection; the first one found to escape fails the whole copy closed rather
than being silently dropped or repaired.

Readiness polling remains loopback-only and does not follow redirects. Invalid
readiness URLs are reported as a coded readiness failure (`125`) rather than an
uncaught traceback. The network declaration is evidence metadata; callers that
need stronger network policy must run this helper inside a network-restricted
runner or container.

## References

MITRE. (2026). *CWE-918: Server-side request forgery (SSRF)*.
https://cwe.mitre.org/data/definitions/918.html
