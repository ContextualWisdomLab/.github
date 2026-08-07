# OpenCode fatal-provider process-group termination

## Incident

The exact-head coverage-evidence job for `.github` pull request #799 reached the repository test suite but did not complete inside its bounded measurement step. A focused reproduction identified `test_fatal_provider_error_kills_hung_opencode_run_early`: the launcher detected a fatal provider event and terminated the `timeout` wrapper, while a descendant fake `opencode` process could remain alive with inherited output pipes. The parent Python process then waited for end-of-file even though the launcher had returned.

## Decision

Each bounded `opencode run` starts in a new session with `setsid`. On a structured fatal-provider event, the launcher sends `SIGTERM` to the negative process-group identifier, waits for bounded group disappearance, and then sends `SIGKILL` to the same group if necessary. The ordinary timeout contract remains `timeout --kill-after=30s`; only the early-fatal cleanup boundary changes.

The group signal is deliberately scoped to the session created for one model attempt. It does not target the workflow shell, unrelated model attempts, or the runner process. The production Ubuntu image already installs `util-linux`, which supplies `setsid`.

## Verification

The existing behavioral regression uses a fake provider that emits a fatal structured event and sleeps for 120 seconds. Before the change, the test exceeded its 30-second subprocess boundary because a descendant retained the capture pipes. With process-group termination, it completes in under 25 seconds and the complete model-pool test file remains eligible for the exact-head coverage job. Shell syntax validation and the repository-wide evidence command remain required before merge.

## Rollback

Rollback requires an independently reviewed change and a replacement mechanism that proves every descendant of a fatal model attempt is reaped without terminating unrelated runner work. Restoring PID-only termination is not acceptable because it reintroduces the pipe-retention failure mode.

## APA 7th references

IEEE & The Open Group. (2024). *The Open Group base specifications issue 8: System interfaces, `kill()`*. https://pubs.opengroup.org/onlinepubs/9799919799/functions/kill.html

Free Software Foundation. (n.d.). *GNU Coreutils manual: `timeout`: Run a command with a time limit*. Retrieved August 7, 2026, from https://www.gnu.org/software/coreutils/manual/html_node/timeout-invocation.html

Linux man-pages project. (2026, February 8). *setsid(2) — Linux manual page* (Linux man-pages 6.18). https://man7.org/linux/man-pages/man2/setsid.2.html
