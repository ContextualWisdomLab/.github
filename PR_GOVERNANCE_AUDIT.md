# PR Governance Audit

Live check: 2026-06-23 KST, GitHub API via `gh` as `seonghobae`.

## Canonical Policy

OpenCode decides; GitHub Actions mutates.

- OpenCode may return only a decision: `UPDATE_BRANCH`, `WAIT`, `REQUEST_CHANGES`, or `NO_ACTION`.
- GitHub Actions updates same-repository PR heads with `expected_head_sha`.
- Old approvals and old checks are not merge evidence after a head SHA changes.
- Merge uses one path: current-head OpenCode approval, no unresolved review threads, required checks green or native auto-merge waiting on them, mergeable head, and no policy blocker.
- Prefer `gh pr merge --auto --merge --match-head-commit <head>` when native auto-merge is enabled.
- Use direct `gh pr merge --merge --match-head-commit <head>` only when the repo policy already allows immediate merge.
- OpenCode app-token merges are deprecated; keep app tokens for review publication, not mechanical branch mutation.
- Tool failures are not source findings. Model failure, API transient, update-branch `422/403`, fork/write-permission failure, conflict, failed checks, and stale review state must be reported as distinct scheduler outcomes.

## Live Repository Inventory

| Repo | Flow | Default | Auto-merge | Branch policy evidence | Workflow footprint | Current gap |
|---|---:|---:|---:|---|---|---|
| `ContextualWisdomLab/.github` | GitHub Flow | `main` | on | ruleset `Lock default branch`; no classic protection | OpenCode Review; PR Review Merge Scheduler; Strix | Current PR #28 has current-head OpenCode success, but OpenCode requests changes because the Strix check fails. |
| `ContextualWisdomLab/ContextualWisdomLab.github.io` | GitHub Flow | `main` | on | ruleset `Lock default branch`; no classic protection | OpenCode Review; PR Review Merge Scheduler; Strix | No representative actor sample checked yet. |
| `ContextualWisdomLab/VibeSec` | Git Flow | `develop` | on | rulesets `Lock default branch`, `PR`; no classic protection | OpenCode Review; PR Review Merge Scheduler; Strix | Mixed human/native auto-merge/GitHub Actions history. |
| `ContextualWisdomLab/bandscope` | Git Flow | `develop` | on | ruleset `Lock default branch`; no classic protection | OpenCode Review; PR Review Merge Scheduler; Strix | No representative actor sample checked yet. |
| `ContextualWisdomLab/clearfolio` | GitHub Flow | `main` | off | ruleset `PR`; no classic protection | OpenCode Review; Strix | Missing PR Review Merge Scheduler and auto-merge is off. |
| `ContextualWisdomLab/codec-carver` | GitHub Flow | `main` | on | ruleset `Lock default branch`; no classic protection | OpenCode Review; legacy Scheduled PR Review Merge; Strix | Replace legacy scheduler with central scheduler. |
| `ContextualWisdomLab/contextual-orchestrator` | GitHub Flow | `main` | off | no ruleset returned | none matched | Needs explicit decision: opt in or keep unmanaged. |
| `ContextualWisdomLab/naruon` | Git Flow | `develop` | on | classic strict required checks `opencode-review`, `strix`; stale dismissal on; rulesets `Lock default branch`, `PR` | OpenCode Review; PR Governance; PR Review Merge Scheduler; Strix self-test; Strix | Canonical source for strict review/coverage behavior. |
| `ContextualWisdomLab/newsdom-api` | Git Flow | `develop` | on | rulesets `Lock default branch`, `mirror-classic-protection-main-develop`; no classic protection | OpenCode Review; PR Review Merge Scheduler; Strix | Open PR queue mostly blocked by review/check state. |
| `ContextualWisdomLab/pg-erd-cloud` | GitHub Flow | `main` | on | ruleset `Lock default branch`; no classic protection | OpenCode Review; PR Review Merge Scheduler; PR Review Autofix/Fix Scheduler; Strix | Good GitHub Actions bot merge samples; extra autofix workflows stay repo-local. |
| `ContextualWisdomLab/scopeweave` | Git Flow | `develop` | on | ruleset `Lock default branch`; no classic protection | OpenCode Review; PR Review Merge Scheduler; Strix self-test; Strix | No representative actor sample checked yet. |

## Representative Evidence

| Repo | Live evidence | Adopt | Reject |
|---|---|---|---|
| `naruon` | `develop`, strict required checks `opencode-review` and `strix`, stale review dismissal enabled. Open PRs #740-#746 show `BEHIND`, `DIRTY`, and `CHANGES_REQUESTED` cases. | Strict current-head evidence and stale-dismissal awareness. | Treating `BEHIND` as merge-ready. |
| `.github` | PR #28 is `MERGEABLE` but `BLOCKED`, with OpenCode `CHANGES_REQUESTED` because coverage/docstring evidence was not proven. | False-approval prevention for missing evidence. | Tooling failure as invented source finding. |
| `pg-erd-cloud` | Recent PRs #236, #237, #239 were merged by `app/github-actions`. | GitHub Actions as mechanical merge actor with head guard. | Human-only queue draining. |
| `codec-carver` | Recent PRs #91 and #92 were merged by `app/opencode-agent`; PR #94 dry-run returns `auto_merge`. | Native auto-merge path for current-head approved PRs. | OpenCode app as merge actor. |
| `VibeSec` | PR #108 had native auto-merge enabled; #106 merged by `app/github-actions`; #109 merged by human. | Keep native auto-merge as preferred waiting path. | Repo-by-repo actor inconsistency. |

## Current Scheduler Contract

The checked-in scheduler already does the minimal central path:

- skips draft, wrong-base, and fork/external-head PRs;
- blocks `DIRTY` or `CONFLICTING`;
- blocks unresolved review threads;
- blocks current-head OpenCode `CHANGES_REQUESTED`;
- blocks current-head failed check runs or status contexts before enabling auto-merge;
- updates `BEHIND` only when the latest OpenCode review is approved, using `expected_head_sha`;
- enables native auto-merge only for current-head OpenCode approval;
- dispatches OpenCode when the current head has no OpenCode decision.

Small proof run:

```text
$ python3 scripts/ci/pr_review_merge_scheduler.py --self-test
self-test passed

$ python3 scripts/ci/pr_review_merge_scheduler.py --repo ContextualWisdomLab/codec-carver --base-branch main --project-flow github-flow --dry-run --max-prs 5
PR #94: auto_merge: current head is approved; auto-merge enabled
{"base_branch": "main", "counts": {"auto_merge": 1}, "dry_run": true, "inspected": 1, "project_flow": "github-flow"}
```

## Rollout List

1. Keep `naruon`, `.github`, `VibeSec`, `bandscope`, `newsdom-api`, `pg-erd-cloud`, and `scopeweave` on `PR Review Merge Scheduler`.
2. Replace `codec-carver` legacy `Scheduled PR Review Merge` with `PR Review Merge Scheduler`.
3. Add `PR Review Merge Scheduler` to `clearfolio` or explicitly mark it unmanaged; auto-merge is currently off.
4. Decide whether `contextual-orchestrator` should join the central PR governance surface; no matching workflows or rulesets were returned.
5. Keep `pg-erd-cloud` autofix workflows repo-local; do not make autofix part of the central merge contract.

## Remaining Proof Gaps

- No live outdated -> update-branch -> new-head review -> merge/auto-merge trace has been completed yet.
- `update-branch` `422/403` behavior still needs a safe fixture or a real blocked case before claiming standardized handling.
- Required-check interpretation should stay delegated to GitHub native auto-merge until a repo needs immediate merge.
- PR #28 itself cannot prove adoption until its current-head coverage/docstring and Strix evidence blockers are resolved.
