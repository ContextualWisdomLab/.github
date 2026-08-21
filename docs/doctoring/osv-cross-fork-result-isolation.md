# OSV cross-fork result isolation

## Failure and root cause

The organization-required `osv-scan` passed both scanner invocations but failed
`Require OSV scan output` because `old-results.json` disappeared. The base
checkout used the upstream repository while the head belonged to a fork.
`actions/checkout` detected the different repository origin and replaced the
workspace before checking out the fork, including the untracked base result.
`clean: false` does not preserve files when checkout must replace a workspace
whose repository identity changed.

## Decision

Write the base result to `/github/runner_temp/old-results.json`, the container
mount for the job-scoped runner temporary directory. After the head checkout,
require that artifact and copy it back to `old-results.json` so the existing
OSV reporter, log, SARIF, and debug-artifact boundaries stay unchanged. Keep the
head result in the current workspace. Missing or empty output remains a hard
failure; this change does not weaken vulnerability comparison.

The workflow also uses OSV Scanner's current `--output-file` spelling instead
of the deprecated `--output` alias.

## Verification and rollback

- The workflow contract proves both base attempts target the runner-temporary
  mount and that the required-output step restores the artifact before use.
- `actionlint` validates the edited workflow.
- Rerun a fork PR's `Security Scan`; both `old-results.json` and
  `new-results.json` must be non-empty before the reporter runs.
- Roll back only after the base and head are scanned in independently named
  workspaces with normalized source paths, or another job-scoped store retains
  the base artifact across repository replacement.

## References

GitHub. (2026). *Variables reference*. GitHub Docs. Retrieved August 22, 2026,
from https://docs.github.com/en/actions/reference/variables-reference

GitHub Actions. (2026). *Checkout*. GitHub. Retrieved August 22, 2026, from
https://github.com/actions/checkout

Google. (2026). *OSV-Scanner*. GitHub. Retrieved August 22, 2026, from
https://github.com/google/osv-scanner
