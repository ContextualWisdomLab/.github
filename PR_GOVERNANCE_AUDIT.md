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

Live generated: 2026-06-23 04:18 KST. PR #28 rechecked: 2026-06-23 11:43 KST.

| Repo | Flow | Default | Auto | Rulesets | Required checks | Stale dismissal | Merge queue | Workflows | Recent merged actor |
|---|---:|---:|---:|---|---|---:|---:|---|---|
| `ContextualWisdomLab/.github` | GitHub Flow | `main` | on | `Lock default branch` | none | true | no | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | #18 `seonghobae`; #17 `seonghobae`; #2 `seonghobae` |
| `ContextualWisdomLab/bandscope` | Git Flow | `develop` | on | `Lock default branch` | `ci / build-and-test`, `dependency-review`, `security-audit`, `CodeQL`, `sbom`, `release-preflight`, `gate / build / windows`, `gate / build / macos`, `trivy-fs-scan` | false | no | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | #427 `github-actions`; #408 `seonghobae`; #405 `seonghobae` |
| `ContextualWisdomLab/clearfolio` | GitHub Flow | `main` | off | `PR` | none | false | no | OpenCode Review; Strix Security Scan | #9 `seonghobae`; #8 `seonghobae`; #7 `seonghobae` |
| `ContextualWisdomLab/codec-carver` | GitHub Flow | `main` | on | `Lock default branch` | none | true | no | OpenCode Review; Scheduled PR Review Merge; Strix Security Scan | #94 `opencode-agent`; #93 `seonghobae`; #90 `seonghobae` |
| `ContextualWisdomLab/contextual-orchestrator` | GitHub Flow | `main` | off | none | none | unknown | unknown | none matched | none |
| `ContextualWisdomLab/ContextualWisdomLab.github.io` | GitHub Flow | `main` | on | `Lock default branch` | none | true | no | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | #15 `seonghobae`; #14 `seonghobae`; #13 `github-actions` auto by `github-actions` |
| `ContextualWisdomLab/naruon` | Git Flow | `develop` | on | `Lock default branch`, `PR` | `opencode-review`, `strix` | true | no | OpenCode Review; PR Governance; PR Review Merge Scheduler; Strix Gate Self-Test; Strix Security Scan | #747 `seonghobae`; #715 `seonghobae`; #692 `seonghobae` |
| `ContextualWisdomLab/newsdom-api` | Git Flow | `develop` | on | `Lock default branch`, `mirror-classic-protection-main-develop` | `codeql (python, actions)`, `dependency-review`, `pytest`, `quality-gate`, `scorecard` | true | no | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | #163 `seonghobae`; #105 `seonghobae`; #162 `seonghobae` |
| `ContextualWisdomLab/pg-erd-cloud` | GitHub Flow | `main` | on | `Lock default branch` | none | true | no | OpenCode Review; PR Review Autofix; PR Review Fix Scheduler; PR Review Merge Scheduler; Strix Security Scan | #239 `github-actions`; #238 `seonghobae`; #236 `github-actions` |
| `ContextualWisdomLab/scopeweave` | Git Flow | `develop` | on | `Lock default branch` | none | true | no | OpenCode Review; PR Review Merge Scheduler; Strix Gate Self-Test; Strix Security Scan | #106 `seonghobae`; #102 `seonghobae`; #101 `seonghobae` auto by `seonghobae` |
| `ContextualWisdomLab/VibeSec` | Git Flow | `develop` | on | `Lock default branch`, `PR` | none | false/true | no | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | #109 `seonghobae`; #67 `github-actions` auto by `github-actions`; #92 `seonghobae` auto by `seonghobae` |

## Current Gaps By Repo

| Repo | Gap |
|---|---|
| `.github` | PR #28 head `60c821e` is blocked by current-head OpenCode `CHANGES_REQUESTED` and `strix` status failure. Same-head manual Strix run `27996904501` passed self-test but failed `Run Strix (quick)`, so it is not merge evidence. |
| `bandscope` | Required checks are repo-specific and broad; keep GitHub native auto-merge as the check interpreter. |
| `clearfolio` | Auto-merge is off and the PR Review Merge Scheduler is missing. |
| `codec-carver` | Latest merged sample #94 still used `opencode-agent`; replace the legacy scheduler with the central GitHub Actions path. |
| `contextual-orchestrator` | No matching rulesets or review workflows; either opt in deliberately or mark unmanaged. |
| `naruon` | Canonical strict check source, but open PRs still need the updated contract observed through one full outdated -> update -> new-head review trace. |
| `newsdom-api` | Ruleset-required checks must stay GitHub-interpreted; open queue is mostly review/check blocked. |
| `pg-erd-cloud` | Good GitHub Actions merge samples; keep autofix workflows repo-local. |
| `scopeweave` | Has central scheduler and Strix self-test, but no current representative update/merge trace captured. |
| `VibeSec` | Actor history is mixed; central scheduler should make GitHub Actions or native auto-merge the only mechanical path. |

## Representative Evidence

| Repo | Live evidence | Adopt | Reject |
|---|---|---|---|
| `naruon` | `develop`, strict required checks `opencode-review` and `strix`, stale review dismissal enabled. Open PRs show `BEHIND`, `DIRTY`, and `CHANGES_REQUESTED` cases. | Strict current-head evidence and stale-dismissal awareness. | Treating `BEHIND` as merge-ready. |
| `.github` | PR #28 is `MERGEABLE` but `BLOCKED`; required PR-target Strix failed on trusted-base self-test, and same-head manual Strix run `27996904501` also failed at `Run Strix (quick)` after publishing `strix` status failure. The latest OpenCode review still cited the stale PR-target Strix URL instead of the same-head manual Strix failure. | Same-head manual evidence for self-modifying trusted workflow changes, plus explicit handling for failed manual evidence. | Treating stale PR-target failure logs as the only current-head diagnosis after a same-head manual Strix rerun exists. |
| `pg-erd-cloud` | Recent PRs #236, #237, #239 were merged by `app/github-actions`. | GitHub Actions as mechanical merge actor with head guard. | Human-only queue draining. |
| `codec-carver` | Recent PR #94 was merged by `app/opencode-agent`, and the repo still has legacy `Scheduled PR Review Merge`. | Native auto-merge path for current-head approved PRs. | OpenCode app as merge actor. |
| `VibeSec` | PR #108 had native auto-merge enabled; #106 merged by `app/github-actions`; #109 merged by human. | Keep native auto-merge as preferred waiting path. | Repo-by-repo actor inconsistency. |

## Current Scheduler Contract

The checked-in scheduler already does the minimal central path:

- skips draft, wrong-base, and fork/external-head PRs;
- blocks `DIRTY` or `CONFLICTING`;
- blocks unresolved review threads;
- blocks current-head OpenCode `CHANGES_REQUESTED`;
- blocks current-head failed check runs or status contexts before enabling auto-merge;
- updates `BEHIND` only when OpenCode approved the exact current head, using `expected_head_sha`;
- enables native auto-merge only for current-head OpenCode approval;
- dispatches OpenCode when the current head has no OpenCode decision.

Small proof run:

```text
$ python3 scripts/ci/pr_review_merge_scheduler.py --self-test
self-test passed

$ python3 scripts/ci/pr_review_merge_scheduler.py --repo ContextualWisdomLab/.github --base-branch main --project-flow github-flow --dry-run --max-prs 40 --no-trigger-reviews
PR #19: block: current-head OpenCode review requested changes
PR #20: block: current-head OpenCode review requested changes
PR #21: block: current-head OpenCode review requested changes
PR #22: block: current-head OpenCode review requested changes
PR #23: block: merge conflict: DIRTY
PR #24: block: current-head OpenCode review requested changes
PR #25: block: current-head OpenCode review requested changes
PR #26: block: current-head OpenCode review requested changes
PR #27: block: current-head OpenCode review requested changes
PR #28: block: current-head OpenCode review requested changes
PR #29: block: current-head OpenCode review requested changes
PR #30: block: current-head OpenCode review requested changes
PR #31: block: current-head OpenCode review requested changes
PR #32: block: current-head OpenCode review requested changes
PR #33: block: current-head OpenCode review requested changes
PR #34: block: current-head OpenCode review requested changes
PR #35: block: current-head OpenCode review requested changes
PR #36: block: current-head OpenCode review requested changes
{"base_branch": "main", "counts": {"block": 18}, "dry_run": true, "inspected": 18, "project_flow": "github-flow"}
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
- PR #28 itself cannot prove adoption until the same-head manual Strix failure is diagnosed and OpenCode stops reusing stale PR-target Strix self-test logs as the only failed-check evidence.
