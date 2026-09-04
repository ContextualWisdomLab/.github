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

Checkout both exact repositories into the same `source/` child directory and
scan that directory. The head checkout may replace `source/` when the repository
identity changes, but the base result remains at the workspace root. Reusing the
same checkout path also gives the base and head scan identical source paths, so
the existing OSV comparison retains its meaning. Missing or empty output remains
a hard failure; this change does not weaken vulnerability comparison.

## Verification and rollback

- The workflow contract proves both checkouts target `source/`, every scan reads
  that same directory, and both result files remain at the workspace root.
- `actionlint` validates the edited workflow.
- Rerun a fork PR's `Security Scan`; both `old-results.json` and
  `new-results.json` must be non-empty before the reporter runs.
- Roll back only after another job-scoped store retains the base artifact across
  repository replacement without changing the compared source paths.

## References

GitHub. (2026). *Variables reference*. GitHub Docs. Retrieved August 22, 2026,
from https://docs.github.com/en/actions/reference/variables-reference

GitHub Actions. (2026). *Checkout*. GitHub. Retrieved August 22, 2026, from
https://github.com/actions/checkout

Google. (2026). *OSV-Scanner*. GitHub. Retrieved August 22, 2026, from
https://github.com/google/osv-scanner
