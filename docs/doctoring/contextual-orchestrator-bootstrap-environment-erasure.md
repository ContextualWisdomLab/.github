# Review sidecar bootstrap environment erasure

**Status:** Proposed · **Date:** 2026-10-02 · **Owner:** ContextualWisdomLab/.github · **Issue:** #1742

## Problem and causal evidence

The long-lived `contextual_orchestrator_review_launcher.py` passed `os.environ`
to `register_review_credentials` and retained all five provider values afterward.
A consumer command running in the same review job could therefore recover a
provider credential from the launcher environment, Linux procfs, or a child
process. This is CWE-526: environment values can cross into dependencies and
other processes that do not need them (MITRE, 2026).

Calling only `os.environ.pop` is insufficient for the Linux procfs boundary.
`/proc/<pid>/environ` addresses the initial environment memory established by
`execve(2)` and does not reflect ordinary environment API changes (Kerrisk,
2026). The repair must overwrite the original value bytes as well as remove the
names from the current mapping.

## Decision

Immediately after the exact call to `register_review_credentials(os.environ)`,
the launcher:

1. overwrites only the value bytes for `BYTEZ_API_KEY`,
   `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`,
   `OPENROUTER_API_KEY`, and `OPENAI_API_KEY` in Linux's original C
   environment block;
2. removes those exact names from `os.environ`; and
3. proceeds to auth lookup, discovery, preflight, and serving only after erasure.

The scan is bounded to 4,096 environment entries and fails closed on Linux if
the C environment symbol is unavailable or no terminator is found. It does not
use a provider-name prefix and preserves unrelated configuration. Non-Linux
runtimes remove the live variables and child inheritance but make no procfs
claim. The process-local KV still holds the credentials required for provider
calls; memory-debugger or KV compromise is outside this environment-transport
repair and remains protected by the runner/process trust boundary.

## Executable regression and boundaries

RED commit `2f6cfda90cca913644b0c8a05db55db6284e07f0` adds a subprocess regression
against protected `main@37b10243cec3d160ecc9c1be75c71428b160a703`; it fails because the scrub
contract does not exist. First GREEN implementation commit
`797cedf26e9bdea234d7034f41e3f808769b1f14` is an ordinary child of that
commit; a subsequent ordinary child narrows regression output so a failing test
cannot serialize unrelated environment entries or secret values. The regression
starts a process with five unique sentinel values and
requires all of the following:

- the live Python environment contains none of the five names;
- Linux `/proc/self/environ` contains none of the sentinel bytes;
- a child process inherits none of the five names; and
- an unrelated environment value remains unchanged in both processes.

False-positive boundary: missing or empty provider variables, unrelated
variables, and non-Linux systems are not findings. False-negative boundary:
a debugger, core dump, or direct access to the process-local KV is not detected
by this regression; those require separate runner/process isolation controls.

## References

Kerrisk, M. (2026). *proc_pid_environ(5)—Linux manual page*. Linux man-pages
project. https://man7.org/linux/man-pages/man5/proc_pid_environ.5.html

MITRE. (2026). *CWE-526: Cleartext storage of sensitive information in an
environment variable* (Version 4.20). https://cwe.mitre.org/data/definitions/526.html


## Exact-head dependency-scan RCA

Security Scan run `36921642491` at head
`8009e029ef5b17cee543e58920194038294c54a1` failed only its Trivy gate.
The five findings were already present on protected `main`: `fast-uri`
3.1.7 (CVE-2026-86472), `ip-address` 10.7.0 (CVE-2026-101911 and
CVE-2026-101912), and `pyo3` 0.22.6 (GHSA-36hh-v3qg-5jq4 and
GHSA-chgr-c6px-7xpp). Test-only commit
`dc35812edcb5e900920264375c088d64acd8cab4` pins the patched target versions before the lock repair. The
ordinary child replaces those inputs with `fast-uri` 3.1.8, `ip-address`
10.7.1, and `pyo3` 0.29.0; it does not exclude fixtures, lower severities,
or weaken the Trivy gate.
