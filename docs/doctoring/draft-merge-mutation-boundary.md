# Draft merge mutation boundary

Decision date: **2026-09-07**

## Problem

The scheduler normally excludes Draft pull requests during inspection. A PR can
change lifecycle state after that decision, or another caller can invoke the
mutation helper directly. Without a second guard, direct merge or auto-merge
could proceed from stale Ready-state authority.

## Decision

`enable_auto_merge` and `merge_pr` retain their cheap caller-snapshot Draft
guard. After dry-run handling and mutation-actor validation, both now call one
shared boundary that reuses the existing direct REST authority read. That read
must prove the same repository and PR number remain open, expose an explicit
Draft value of `false`, and retain the expected exact head. Missing, malformed,
closed, Draft, or moved-head evidence fails closed before `gh pr merge`.

This boundary is intentionally inside both mutation entrypoints. The earlier
`inspect_pr` approval revalidation remains useful, but cannot protect a direct
caller or a lifecycle transition occurring after that decision-level check.
`--match-head-commit` remains the final GitHub head guard; it does not replace
the live Draft-state check.

## Failure scenes

- A Ready snapshot becomes Draft on the same head: mutation is refused.
- The PR closes, becomes unavailable, or returns malformed authority: mutation
  is refused.
- The head changes after inspection: mutation is refused before GitHub CLI.
- A direct helper call supplies a Draft PR: no GitHub command is executed.
- A freshly open, non-Draft PR on the expected head follows the existing
  guarded merge flow unchanged.

## Evidence and follow-up

The original RED `2d140a84203a0df0cb86cd6b6ab31fc37bbdbda2`
covered only an already-Draft caller snapshot. Corrective RED `1afea4e` covers
both mutation entrypoints across same-head Ready→Draft, moved-head, missing-PR,
and exact-ready cases. The focused scheduler suite passes locally under
`GITHUB_ACTIONS=true` and `-W error`; fresh exact-head hosted checks and
independent review remain required.

## Reference

GitHub. (2026). *Pull requests and draft pull requests*.
https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests
