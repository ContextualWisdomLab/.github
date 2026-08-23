# Actionlint modern-schema and permissive shell-parser compatibility

Decision date: **2026-08-22**

## Incident

The write-capable PR autofix worker validates every workflow it changes with
`actionlint`. Two upstream gaps can make that fail or stall even when GitHub
accepts the workflow.

1. GitHub Actions supports `queue: max` for concurrency groups, while released
   actionlint 1.7.12 still reports that key as invalid. Upstream pull request
   654 tracks schema support.
2. Actionlint can deadlock while sending a workflow `run` block larger than a
   pipe buffer to its ShellCheck subprocess. Upstream issue 712 reproduces the
   boundary at 64 KiB. The central OpenCode review workflow contains larger
   trusted shell blocks, so an autofix touching it can wait indefinitely.

These are linter transport/schema gaps, not reasons to remove workflow schema
validation or shell analysis.

## Decision

Keep actionlint as the schema, expression, and Pyflakes validator, but disable
its ShellCheck subprocess integration with `-shellcheck=`. The trusted
`lint_github_workflows.rb` boundary uses Ruby's standard-library Psych parser to
read the same YAML scalar values, reproduces actionlint 1.7.12's workflow/job/
runner/step shell precedence, expression normalization, and implicit shell
setup. It streams each Bash or POSIX sh program into shfmt 3.13.1's syntax-tree
JSON mode and fails closed on syntax errors, malformed JSON, or a missing
executable.

shfmt is BSD-3-Clause, which satisfies the binding commercial/permissive
license policy; the newly introduced direct GPL-3.0-or-later ShellCheck
dependency has been removed. The write-capable worker downloads the official
Linux amd64 actionlint 1.7.12 archive and shfmt 3.13.1 binary only when a
workflow changed, verifies both published SHA-256 digests, extracts only the
actionlint executable, and exposes only those verified executables through the
step-local `PATH`. This avoids relying on an undocumented runner-image tool
inventory while preserving fail-closed schema validation. Behavioral tests use
an isolated temporary `PATH` to prove the same fixed executable and argv
boundary.

[Required Semgrep run 32637664667](https://github.com/ContextualWisdomLab/.github/actions/runs/32637664667)
still classified the fixed `actionlint` invocation as dynamic because workflow
paths remain argv values. Ruby's `Open3.capture3` passes these separate
arguments directly to the literal executable and does not invoke a shell. The
single inline Semgrep suppression therefore applies only to that reviewed
false positive; the executable-name regression, isolated `PATH` execution, and
fail-closed actionlint status handling remain mandatory. shfmt uses only
literal command arguments and receives the governed shell source through
standard input, so it needs no scanner suppression.

The autofix worker ignores only actionlint's exact released-schema diagnostic
for the concurrency `queue` key. Before linting, it rejects every changed
workflow whose `queue` value is not exactly `max`; therefore the compatibility
exception cannot admit an invented queue mode. GitHub permits `queue: max` only
when `cancel-in-progress` is false or absent, so a statically true cancellation
setting is also rejected at both workflow and job scope before actionlint runs.

This is a temporary compatibility boundary. Remove the queue diagnostic
exception after an actionlint release containing pull request 654 is pinned.
Remove the shfmt parser boundary only after issue 712 is fixed, actionlint ships
the corrected transport, its effective shell dependency satisfies the binding
license policy, and a greater-than-64-KiB regression passes through that
replacement.

## Verification

- A greater-than-64-KiB synthetic shell program reaches the delegated shfmt
  parser through the bounded Ruby subprocess transport without content loss.
- Bash, sh, Windows/PowerShell, Python, workflow defaults, and GitHub expression
  normalization retain actionlint's effective-shell behavior.
- shfmt syntax failures, malformed result JSON, actionlint failures, invalid
  concurrency queue values, and `queue: max` plus static cancellation all fail
  closed with actionable workflow context.
- The offline Python-only coverage sandbox records the Ruby subprocess
  contracts as unavailable instead of failing with `FileNotFoundError`; the
  hosted quality job, whose runner includes Ruby, executes those contracts and
  the real all-workflow lint command. The write-capable runtime does not assume
  that actionlint is preinstalled: its exact release archive is checksum-pinned
  beside shfmt before the linter starts.

## References

GitHub. (2026, May 7). *GitHub Actions concurrency groups now allow larger
queues*. https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/

Martí, D. (2026, April 6). *shfmt v3.13.1* [Computer software]. GitHub.
https://github.com/mvdan/sh/releases/tag/v3.13.1

Martí, D. (n.d.). *mvdan/sh license* [BSD 3-Clause license]. GitHub. Retrieved
August 23, 2026, from https://github.com/mvdan/sh/blob/master/LICENSE

Murai, R. (2025). *Support queue: max in concurrency* [Pull request #654].
GitHub. https://github.com/rhysd/actionlint/pull/654

Murai, R. (2026, March 30). *actionlint v1.7.12* [Computer software]. GitHub.
https://github.com/rhysd/actionlint/releases/tag/v1.7.12

Murai, R. (2026). *Shellcheck integration deadlocks for run blocks greater than
64 KiB* [Issue #712]. GitHub. https://github.com/rhysd/actionlint/issues/712
