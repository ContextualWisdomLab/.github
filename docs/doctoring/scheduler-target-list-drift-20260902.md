# Doctoring record: scheduler target-list drift (2026-09-02)

## Incident

`hourly-review-repair.yml`'s per-cron `target_repository` matrix and the
`OPENCODE_REPOSITORY_DISPATCH_TARGETS` repository variable (which gates
`ALLOWED_TARGET_REPOSITORIES` in `pr-review-merge-scheduler.yml` /
`pr-review-fix-scheduler.yml`, and the agent-mention dispatch allowlist) are
two independently hand-maintained lists of "repositories legitimately
targetable by an OpenCode-driven dispatch." They have no structural link:
adding a repository to one does not add it to the other.

This caused three real, silent failures, all discovered and fixed the same
day:

- `governance-risk-compliance` — added to the hourly matrix (run
  `.github/actions/runs/33524178483/job/99910668839`, 2026-09-01) before the
  variable was updated; every hourly heartbeat failed with `##[error]Scheduler
  target repository is not allowlisted: ContextualWisdomLab/governance-risk-compliance.`
  A prior fix attempt (commit `7bf98d0`) hardcoded the repository name
  directly into both scheduler workflows as a "temporary propagation bridge"
  instead of fixing the variable — this violated this repo's own thin-caller
  convention (`CLAUDE.md`: "Product hourly callers stay thin. Do not
  hard-code ... into `pr-review-fix-scheduler.yml`") and broke
  `test_no_target_repository_is_hard_coded_in_the_shared_scheduler` on `main`.
  Fixed properly in `contextual-orchestrator#1028`'s sibling PR here
  (`fix(scheduler): admit governance-risk-compliance via the org variable, not
  a hardcode`, #1743): added the repository to the variable directly, removed
  the hardcode.
- `nonnest2` and `quarantine-sandbox-runtime` — found by diffing the hourly
  matrix's target list against the live variable's value while scoping this
  fix: both were present in the hourly matrix (present since the original
  18-file-to-1 consolidation, ADR-0021) but absent from the variable,
  meaning their hourly heartbeat had been failing closed the same way,
  undetected because the queue backlog this session was separately
  investigating (a hard 60-concurrent-job org plan limit, confirmed via the
  GitHub Actions Settings UI) meant these runs weren't being watched
  individually. Fixed the same way: added both to the variable.

## Root cause

Not a logic bug in either scheduler — `target_allowed` fails closed exactly
as designed when a target isn't in the allowlist, which is correct behavior
for an *actually* unauthorized target. The defect is that there is no
mechanism keeping the two lists in sync, and no test catching a PR that adds
a repository to one list without the other.

## Fix

- `scripts/ci/opencode_repository_dispatch_targets.json` — a new,
  hand-maintained mirror of `OPENCODE_REPOSITORY_DISPATCH_TARGETS`'s live
  value (there is no API to commit a repository variable's value to source
  control, so this file is deliberately a mirror, not a generator — whoever
  updates the live variable updates this file in the same PR, per the file's
  own header comment).
- `tests/test_hourly_review_repair_callers.py::test_every_hourly_caller_target_is_in_the_dispatch_targets_mirror` —
  asserts every `target_repository` in `hourly-review-repair.yml`'s
  `_EXPECTED_TARGETS` (the existing, already-tested canonical model of the
  workflow's `case` statement) is present in the mirror. A future PR that
  adds a repository to the hourly matrix without also updating the mirror
  (and, by the mirror's own documented discipline, the live variable) now
  fails this test at review time instead of failing the next hourly
  heartbeat silently.

## What this does not do

This does not verify the mirror file's contents actually match the live
variable's *current* value — that would require a network call to the
GitHub API at test time, which this repo's offline `pytest tests` suite
deliberately does not do (see `pyproject.toml`'s `pythonpath` setup; every
other contract test in this module is a pure file-content assertion). A
mismatch between the mirror and the live variable (e.g. someone runs `gh
variable set` without updating this file, or vice versa) is not caught by
this test — only a mismatch between the *workflow matrix* and the mirror is.
Closing that remaining gap (verifying the mirror against the live variable)
needs either a step in an existing regularly-running workflow or a documented
manual verification command, and was deliberately left out of this fix to
keep it a pure test addition with zero production-workflow risk; see the
open item below.

## Follow-up (not done here, deliberately out of scope for this fix)

Add a live-verification step (in an existing workflow, not a new one, per
this session's org-culture reasoning: prefer a loud contract-test-style
failure a human must resolve with an explicit commit over an
auto-mutating workflow that "magically" fixes drift) that fetches
`OPENCODE_REPOSITORY_DISPATCH_TARGETS`'s live value and fails loudly if it
diverges from `scripts/ci/opencode_repository_dispatch_targets.json`. Left
open pending a decision on which existing workflow should host that step.
