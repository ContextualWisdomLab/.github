# Central `.github` hourly OpenCode conflict repair

## Decision

The central repository scans its own open `main` pull requests once per hour and
dispatches the existing trusted OpenCode conflict worker for a same-repository
head reported by GitHub as `DIRTY` or `CONFLICTING`.

A review is **not** a prerequisite for this bounded repair. Resolving the
conflict creates a new merge commit and therefore a new pull-request head; any
review of the old head cannot establish approval of the resulting combined
source. The repaired head must complete fresh review and required checks before
it can merge.

Direct Python-library callers retain the historical approval prerequisite. The
trusted reusable workflow opts into unreviewed conflict repair explicitly with
`--resolve-unreviewed-conflicts`, making the privilege visible and testable.

## Execution path

```text
hourly protected-default-branch caller
→ exact open PR inventory
→ same-repository, non-draft, configured-base filter
→ GitHub DIRTY / CONFLICTING signal
→ head-scoped retry marker
→ repository_dispatch(pr-review-autofix, repair_mode=conflict)
→ exact live base/head revalidation
→ git merge --no-commit --no-ff <base_sha>
→ sealed NUL-delimited conflicted-path allowlist
→ whole-worktree snapshot outside the repository
→ OpenCode edits conflicted paths only
→ scope verification, conflict-marker rejection, syntax checks
→ live-head race check
→ merge commit push
→ fresh required reviews and checks
```

## Preserved security and governance boundaries

- Draft pull requests remain ineligible.
- Fork and external-head pull requests remain read-only.
- The configured base branch must match.
- The worker refetches and validates the exact live base and head before writing.
- OpenCode receives no GitHub token, OIDC request token, shell permission,
  external-directory permission, web access, task delegation, or arbitrary
  JavaScript execution permission.
- The model may modify only paths Git reported as unmerged.
- Tracked, untracked, ignored, deleted, retargeted, and symbolic-link state is
  included in the scope evidence.
- Unresolved conflict markers fail closed.
- A concurrent head movement prevents the push.
- Conflict repair never approves, merges, or releases the pull request; it only
  produces a reviewable combined head.
- One repair is dispatched per scheduler pass, with a one-hour exact-head retry
  interval and non-cancelling worker concurrency.
- `COPILOT_GITHUB_TOKEN` is not used.

## Why approval-before-repair was removed from the scheduled path

The previous selector required a current-head approval before conflict repair.
That created a circular dependency for PRs such as `.github#1098`: reviewers
could not assess a valid merge preview while the conflict prevented the safe
combined head from existing, and the conflict worker could not run until a
review approved the pre-resolution head.

The correct evidence order is:

```text
conflict detected
→ bounded mechanical/semantic repair
→ new exact head
→ review and checks on that exact head
→ guarded merge decision
```

This changes eligibility only. It does not weaken the worker's write boundary or
the repository's review, required-check, branch-protection, and merge gates.

## Regression evidence

`tests/test_github_hourly_conflict_repair.py` fixes the following contracts:

1. An unreviewed `DIRTY` PR becomes eligible only when the trusted policy flag is
   explicit.
2. Direct library use remains backward-compatible by default.
3. The CLI exposes the policy flag.
4. The reusable workflow enables the policy for hourly callers by default.
5. `.github` has its own hourly caller at minute 21.
6. A same-repository protected caller does not require a cross-repository target
   allowlist entry, while cross-repository targets still do.
7. The focused NVIDIA NIM review-repair gate tracks the caller, regression test,
   and this doctoring record.

The pre-existing conflict-scope, control-file isolation, trusted Git executable,
ignored-path, symlink-target, exact-head, writer-security, and NVIDIA NIM
contract suites remain authoritative for the worker boundary.

## Operator next action

After this change reaches `main`, inspect the next `Central GitHub Hourly Review
Repair` run. A qualifying conflict should receive the head-scoped scheduler
marker, followed by a `PR Review Autofix` conflict-mode run. Confirm that the
new head has a merge commit whose parents are the previous PR head and the live
protected base, then require normal current-head reviews and checks before
merging.

## References — APA 7th

GitHub. (n.d.). *About protected branches*. GitHub Docs.
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *Resolving a merge conflict using the command line*. GitHub Docs.
https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/addressing-merge-conflicts/resolving-a-merge-conflict-using-the-command-line

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218
