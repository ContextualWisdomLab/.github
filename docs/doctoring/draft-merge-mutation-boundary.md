# Draft merge mutation boundary

Decision date: **2026-09-07**

## Problem

The scheduler normally excludes Draft pull requests during inspection. A PR can
change lifecycle state after that decision, or another caller can invoke the
mutation helper directly. Without a second guard, direct merge or auto-merge
could proceed from stale Ready-state authority.

## Decision

`enable_auto_merge` and `merge_pr` each reject `isDraft` before actor
validation, head-SHA processing, or any GitHub command. The upstream decision
filter remains in place; this is a minimal defense-in-depth invariant at the
irreversible boundary.

## Failure scenes

- A Ready PR becomes Draft after inspection: mutation is refused.
- A direct helper call supplies a Draft PR: no GitHub command is executed.
- A non-Draft PR follows the existing guarded expected-head flow unchanged.

## Evidence and follow-up

RED commit: `2d140a84203a0df0cb86cd6b6ab31fc37bbdbda2`.
Fresh exact-head hosted checks and independent review remain required.

## Reference

GitHub. (2026). *Pull requests and draft pull requests*.
https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests
