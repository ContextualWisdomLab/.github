# Sidecar CPython shared-library binding

## Status

Proposed common startup repair; protected hosted acceptance remains unverified.

## Evidence and root cause

Naruon #1795 Noema and Strix both exited 139 in the offline gateway fixture on
`cwlab-s1-02`, before live provider calls, at pinned orchestrator
`01bf92a3ec67a0e1f9b68978eb16b60301e985fd`.
Their selected executable was toolcache Python `3.12.14/x64/bin/python`.
The composite action intentionally uses `update-environment: false`; Strix
retained the consumer `3.13.15/x64/lib` in `LD_LIBRARY_PATH`.

A read-only runtime comparison on that same guest on 2026-09-27 UTC
found that the selected executable, without its matching library path, reported
Python **3.12.3** while reading the toolcache 3.12.14 standard library and
`_asyncio` extension. The complete offline fixture, exact source and binary-only
hash-pinned dependencies installed in a new owned environment, passed under
system Python 3.12.3. Keeping those dependency bytes and switching to the
selected toolcache executable reproduced SIGSEGV at `logging.LogRecord`,
`asyncio.current_task()` in the HTTP request thread. Only `_cffi_backend` was
listed as an external extension in the fatal trace; this is not evidence of a
provider or fast-mlsirm defect.

Prepending the selected toolcache's `lib` directory made the entire fixture
pass. The actual patched shell selection also passed with the stale consumer
3.13 library path supplied. No shared installation, service, runner registration,
group grant or existing job was modified.

## Repair and verification

Resolve the selected executable (including symlinks and PATH lookup), then
prepend its adjacent library directory only when `libpython3.12.so.1.0` exists.
Keep the existing library search path as a suffix and keep this environment
inside the sidecar shell process. Python 3.12 validation, dependency hashes,
all offline assertions, provider discovery and review gates remain enforced.

The behavioral regression fails on unmodified main and passes after the repair;
it covers symlink resolution, matching-library precedence and absent-library
fallback. Local sidecar contracts: 31 passed. With `GITHUB_ACTIONS=true`, warnings
as errors and pytest plugin autoload disabled: 168 sidecar, runtime-preflight
and composite-action contracts passed in 16.68 seconds. Bash syntax, Ruff and
`git diff --check` pass. Linux real-fixture comparison additionally exercised
imports, server creation, rejection logging, large request, tool descriptions
and shutdown. Hosted exact-head review and full live-provider acceptance are
still required.
