# OpenCode fatal-provider process-group termination

## Incident

The exact-head coverage-evidence job for `.github` pull request #799 reached the repository test suite but did not complete inside its bounded measurement step. A focused reproduction identified `test_fatal_provider_error_kills_hung_opencode_run_early`: the launcher detected a fatal provider event and terminated the `timeout` wrapper, while a descendant fake `opencode` process could remain alive with inherited output pipes. The parent Python process then waited for end-of-file even though the launcher had returned.

## Decision

Each bounded `opencode run` starts in a new session with `setsid` when that
tool is present (Linux CI / util-linux). On a structured fatal-provider
event, the launcher sends `SIGTERM` to the negative process-group
identifier, waits for bounded group disappearance, and then sends
`SIGKILL` to the same group if necessary. Darwin local runners without
`setsid` keep PID-directed `TERM`/`KILL` so the repository suite still
executes. The ordinary timeout contract remains
`timeout --kill-after=30s`; only the early-fatal cleanup boundary
changes.

The launcher explicitly disables Bash job control before it starts an
attempt. That preserves the POSIX identity relied on by the negative-PGID
signal: the background `setsid` process executes directly, and its PID becomes
the new session and process-group id. The implementation captures that id at
launch time instead of probing `PATH` again during cleanup.

The group signal is deliberately scoped to the session created for one model attempt. It does not target the workflow shell, unrelated model attempts, or the runner process. The production Ubuntu image already installs `util-linux`, which supplies `setsid`.

CWE-400 describes uncontrolled resource consumption when a child outlives the
intended bound (MITRE, 2026). NIST SP 800-53 Rev. 5 SI-4 requires monitoring
that detects and contains anomalous process behavior rather than treating a
returned parent as a complete cleanup (Joint Task Force, 2020). Killing only
the `timeout` wrapper therefore leaves a descendant that can stall coverage
evidence; the negative process-group identifier is the contained unit.

## Verification

The existing behavioral regressions in
`tests/test_opencode_model_pool_runner.py` use fake providers that emit fatal
structured events and sleep for 120 seconds. Before the change, the tests
exceeded their subprocess boundary because a descendant retained the capture
pipes. With process-group termination, both the context/quota and delisted-model
cases complete in under 25 seconds. The focused workflow executes those real
process tests on Ubuntu, and shell syntax plus the repository-wide evidence
command remain required before merge.

## Rollback

Rollback requires an independently reviewed change and a replacement mechanism that proves every descendant of a fatal model attempt is reaped without terminating unrelated runner work. Restoring PID-only termination is not acceptable because it reintroduces the pipe-retention failure mode.

## APA 7th references

IEEE & The Open Group. (2024). *The Open Group base specifications issue 8: System interfaces, `kill()`*. https://pubs.opengroup.org/onlinepubs/9799919799/functions/kill.html

Joint Task Force. (2020). *Security and privacy controls for information systems
and organizations* (NIST SP 800-53 Rev. 5). National Institute of Standards and
Technology. https://doi.org/10.6028/NIST.SP.800-53r5

MITRE. (2026). *CWE-400: Uncontrolled resource consumption*.
https://cwe.mitre.org/data/definitions/400.html

Free Software Foundation. (n.d.). *GNU Coreutils manual: `timeout`: Run a command with a time limit*. Retrieved August 7, 2026, from https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html

Linux man-pages project. (2026, February 8). *setsid(2) — Linux manual page* (Linux man-pages 6.18). https://man7.org/linux/man-pages/man2/setsid.2.html
