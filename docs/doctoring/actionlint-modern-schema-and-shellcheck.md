# Actionlint modern-schema and large-shell compatibility

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
only its ShellCheck subprocess integration with `-shellcheck=`. The trusted
`lint_github_workflows.rb` boundary uses Ruby's standard-library Psych parser to
read the same YAML scalar values, reproduces actionlint 1.7.12's workflow/job/
runner/step shell precedence, expression normalization, implicit shell setup,
and narrow rule exclusions, and invokes the installed ShellCheck against unique
regular temporary files. It parses ShellCheck JSON, restores the workflow job
and step identity in every diagnostic, preserves findings as a failing status,
and fails closed on malformed output or a missing executable.

The helper invokes the fixed `actionlint` and `shellcheck` executable names as
argv, never a repository- or environment-selected command and never a shell
string. The pinned hosted setup supplies those names through its trusted
`PATH`; behavioral tests use an isolated temporary `PATH` to prove the same
argv boundary without introducing a second executable-selection channel.

The autofix worker ignores only actionlint's exact released-schema diagnostic
for the concurrency `queue` key. Before linting, it rejects every changed
workflow whose `queue` value is not exactly `max`; therefore the compatibility
exception cannot admit an invented queue mode.

This is a temporary compatibility boundary. Remove the queue diagnostic
exception after an actionlint release containing pull request 654 is pinned.
Remove the stdin spool only after issue 712 is fixed and a greater-than-64-KiB
regression passes directly through the pinned actionlint/ShellCheck pair.

## Verification

- A greater-than-64-KiB synthetic shell program reaches the delegated
  ShellCheck executable through a regular file, without content loss.
- Bash, sh, Windows/PowerShell, Python, workflow defaults, and GitHub expression
  normalization retain actionlint's effective-shell behavior.
- ShellCheck findings, malformed result JSON, actionlint failures, and invalid
  concurrency queue values all fail closed with actionable workflow context.
- The offline Python-only coverage sandbox records the Ruby subprocess
  contracts as unavailable instead of failing with `FileNotFoundError`; the
  hosted quality job, whose runner includes Ruby, executes those contracts and
  the real all-workflow lint command.

## References

GitHub. (2026, May 7). *GitHub Actions concurrency groups now allow larger
queues*. https://github.blog/changelog/2026-05-07-github-actions-concurrency-groups-now-allow-larger-queues/

Murai, R. (2025). *Support queue: max in concurrency* [Pull request #654].
GitHub. https://github.com/rhysd/actionlint/pull/654

Murai, R. (2026). *Shellcheck integration deadlocks for run blocks greater than
64 KiB* [Issue #712]. GitHub. https://github.com/rhysd/actionlint/issues/712
