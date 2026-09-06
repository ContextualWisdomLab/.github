# OSV cross-fork result isolation

## Failure and root cause

The organization-required `osv-scan` passed both scanner invocations but failed
`Require OSV scan output` because `old-results.json` disappeared. The base
checkout used the upstream repository while the head belonged to a fork.
`actions/checkout` detected the different repository origin and replaced the
workspace before checking out the fork, including the untracked base result.
`clean: false` does not preserve files when checkout must replace a workspace
whose repository identity changed. Copying a captured result back onto the
workspace `old-results.json` can also fail: the scanner action may create that
file as root, so a runner-user overwrite returns permission denied.
The inverse copy has the same unowned boundary: a runner-user `cp` can read a
root-owned scanner result only while the container happens to leave it
world-readable. A mode such as `0600` makes that capture fail before the
checkout-isolation guarantee can be established.

## Decision

Checkout both exact repositories into the same `source/` child directory and
scan that directory. Copy a non-empty scanner result into
`${RUNNER_TEMP}/osv-old-results.json` and `${RUNNER_TEMP}/osv-new-results.json`
immediately after each scan. Do not copy those captures back onto an existing
workspace `old-results.json`: the OSV action may create that file as root, and
a runner-user `cp` then fails with permission denied (observed on
ContextualWisdomLab/.github#1257). For the scanner-to-runner transfer, accept
only a fixed-path, non-empty regular file that is not a symbolic link, use the
GitHub-hosted Linux runner's passwordless `/usr/bin/sudo` solely for a fixed
`/usr/bin/cat`, and let the unprivileged shell create the destination after
`umask 077`. The resulting `RUNNER_TEMP` capture is therefore runner-owned and
mode `0600`; the workflow verifies both ownership and non-empty content. It
does not `chmod` the scanner output, grant other users read access, or make the
reporter privileged. Keep the base capture outside the workspace throughout
the head scan; no consumer needs a pre-scan workspace copy. Materialize both
reporter inputs exactly once by unlinking the scanner-created workspace files
and copying from `RUNNER_TEMP`. Discard `source/old-results.json` and
`source/new-results.json` as exact paths before each scan, whether a fork plants
a file, link, or directory there, so the planted entry cannot abort the scan or
become reporter input. After the head checkout, never treat checkout-path JSON
as scanner output. Missing or empty captured output remains a hard failure; a
zero-finding head scan does not skip the base comparison. This change does not
weaken vulnerability comparison. The always-run debug upload reads the private
runner captures directly rather than root-owned workspace results, so an early
failure does not replace the primary diagnostic with an artifact permission
error.

## Verification and rollback

- The workflow contract proves both checkouts target `source/`, every scan reads
  that same directory, captures land in `RUNNER_TEMP` before compare, reporter
  materialization unlinks before copy, and post-checkout `source/*.json` is not
  reporter input.
- The executable regression runs both production capture steps against an
  unreadable scanner result through a bounded privilege stand-in, then proves
  the capture contains the exact result and is runner-owned with mode `0600`.
- The artifact contract uploads the runner-owned captures, including on failure,
  and never asks the uploader to read root-owned workspace result files.
- `actionlint` validates the edited workflow.
- Rerun a fork PR's `Security Scan`; both captured result files must be
  non-empty before the reporter runs.
- Roll back only after another job-scoped store retains the base artifact across
  repository replacement without changing the compared source paths.

## References

GitHub. (2026). *Variables reference*. GitHub Docs. Retrieved August 22, 2026,
from https://docs.github.com/en/actions/reference/variables-reference

GitHub. (2026). *GitHub-hosted runners reference*. GitHub Docs. Retrieved
August 23, 2026, from
https://docs.github.com/en/actions/reference/runners/github-hosted-runners

GitHub Actions. (2026). *Checkout*. GitHub. Retrieved August 22, 2026, from
https://github.com/actions/checkout

Google. (2026). *OSV-Scanner*. GitHub. Retrieved August 22, 2026, from
https://github.com/google/osv-scanner
