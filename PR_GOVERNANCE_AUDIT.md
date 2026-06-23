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
- OpenCode approval publication must be bounded. Peer GitHub Checks can be awaited, but the approval step itself must time out instead of running for hours; the current central limit is a 45 minute approval step with 81 peer-check probes at 30 seconds.
- Tool failures are not source findings. Model failure, API transient, update-branch `422/403`, fork/write-permission failure, conflict, failed checks, and stale review state must be reported as distinct scheduler outcomes.

## Live Repository Inventory

Live generated: 2026-06-23 04:18 KST. PR #28 post-merge refresh: 2026-06-23 16:05 KST. PR #37 post-merge refresh: 2026-06-23 21:50 KST.

| Repo | Flow | Default | Auto | Rulesets | Required checks | Stale dismissal | Merge queue | Workflows | Recent merged actor |
|---|---:|---:|---:|---|---|---:|---:|---|---|
| `ContextualWisdomLab/.github` | GitHub Flow | `main` | on | `Lock default branch` | none | true | no | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | #28 `seonghobae` merge `a025be1`; #18 `seonghobae`; #17 `seonghobae` |
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
| `.github` | PR #37 is merged at `3c3695f` after current-head Strix run `28025893898`, current-head manual OpenCode run `28026724674`, unresolved review threads `0`, and guarded merge against head `8b25761`. Remaining open PRs #19-#27 and #29-#36 are still blocked by `CHANGES_REQUESTED` and/or `DIRTY`. |
| `bandscope` | Required checks are repo-specific and broad; keep GitHub native auto-merge as the check interpreter. |
| `clearfolio` | Auto-merge is off. PR #13 adds the central PR Review Merge Scheduler and `opencode.jsonc`; current PR-target Strix still fails because base `strix.yml` does not copy PR-head `opencode.jsonc` into the trusted workspace. |
| `codec-carver` | Latest merged sample #94 still used `opencode-agent`; PR #98 replaces the legacy scheduler with the central GitHub Actions path and is waiting on existing OpenCode/Strix checks. |
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
| `.github` | PR #28 head `811446d` reached current-head approval after manual Strix run `28007326148` published a successful `strix` status and manual OpenCode run `28008174977` approved the same head; it was merged by `seonghobae` with merge commit `a025be1`. The earlier PR-target Strix failure remains useful only as the reason same-head manual evidence was required. | Same-head manual evidence for self-modifying trusted workflow changes, current-head OpenCode approval, unresolved thread check, and `--match-head-commit` guarded merge. | Treating stale PR-target failure logs as merge blockers after newer same-head evidence exists. |
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
- dispatches same-head Strix evidence first when the current head has no completed Strix evidence;
- waits while same-head Strix evidence is still running, so OpenCode is not started just to poll a peer check;
- dispatches OpenCode only after same-head Strix evidence is complete, including failed Strix evidence that OpenCode must explain from logs.

Small proof run:

```text
$ python3 scripts/ci/pr_review_merge_scheduler.py --self-test
self-test passed

$ python3 scripts/ci/pr_review_merge_scheduler.py --repo ContextualWisdomLab/.github --base-branch main --project-flow github-flow --dry-run --max-prs 40 --no-trigger-reviews
PR #19: block: merge conflict: DIRTY
PR #20: block: merge conflict: DIRTY
PR #21: block: current-head OpenCode review requested changes
PR #22: block: merge conflict: DIRTY
PR #23: block: merge conflict: DIRTY
PR #24: block: current-head OpenCode review requested changes
PR #25: block: current-head OpenCode review requested changes
PR #26: block: current-head OpenCode review requested changes
PR #27: block: current-head OpenCode review requested changes
PR #29: block: current-head OpenCode review requested changes
PR #30: block: current-head OpenCode review requested changes
PR #31: block: current-head OpenCode review requested changes
PR #32: block: current-head OpenCode review requested changes
PR #33: block: current-head OpenCode review requested changes
PR #34: block: current-head OpenCode review requested changes
PR #35: block: current-head OpenCode review requested changes
PR #36: block: merge conflict: DIRTY
{"base_branch": "main", "counts": {"block": 17}, "dry_run": true, "inspected": 17, "project_flow": "github-flow"}
```

## Rollout List

1. Keep `naruon`, `.github`, `VibeSec`, `bandscope`, `newsdom-api`, `pg-erd-cloud`, and `scopeweave` on `PR Review Merge Scheduler`.
2. Merge `codec-carver` PR #98 to replace legacy `Scheduled PR Review Merge` with `PR Review Merge Scheduler`; current checks were still in progress at the 2026-06-23 22:13 KST snapshot.
3. Resolve `clearfolio` PR #13's trusted-base Strix blocker, then merge it to add `PR Review Merge Scheduler`; auto-merge is currently off.
4. Decide whether `contextual-orchestrator` should join the central PR governance surface; no matching workflows or rulesets were returned.
5. Keep `pg-erd-cloud` autofix workflows repo-local; do not make autofix part of the central merge contract.

## Remaining Proof Gaps

- A live current-head review -> same-head manual Strix status bridge -> OpenCode approval -> guarded merge trace has been completed on `.github` PR #28.
- No live outdated -> update-branch -> new-head review -> merge/auto-merge trace has been completed yet.
- `update-branch` `422/403` behavior still needs a safe fixture or a real blocked case before claiming standardized handling.
- Required-check interpretation should stay delegated to GitHub native auto-merge until a repo needs immediate merge.
- PR #28 proves the self-modifying trusted workflow bootstrap path after newer same-head evidence exists, but it does not prove update-branch behavior, stale approval dismissal after a head change, or cross-repository rollout.
- PR #37 adds a bounded OpenCode approval publication timeout after manual current-head OpenCode run `28011338113` reached the approval step and was observed waiting on peer checks instead of finishing promptly.
- PR #37 current-head run `28012303665` proved 100% coverage/docstring evidence and OpenCode completion for head `184be63`; Strix run `28012303876` proved same-head manual Strix success. The run also exposed that cancelled PR-target helper check `Strix Security Scan/publish-manual-pr-evidence-status` must be superseded by the newer same-head manual `strix` status, not treated as a source finding.
- PR #37 head `9bbf641` exposed a remaining race: OpenCode can finish before same-head manual Strix publishes the superseding `strix` status, causing stale cancelled PR-target Strix checks to become REQUEST_CHANGES. The evidence preparation step now waits, within a 40 minute bound, whenever peer checks are still running, even if completed failed check evidence is already visible.
- The same race also showed that PR `statusCheckRollup` does not see a manual Strix `workflow_dispatch` run until it publishes a commit status. OpenCode evidence preparation now queries current-head `strix.yml` workflow runs directly and treats in-progress same-head Strix runs as peer checks.
- Strix run `28014156427` also reported sensitive log disclosure risk in failed-check evidence handling. The collector now redacts common token, API key, password, secret, authorization, Slack token, and AWS access-key patterns before any failed logs are summarized or embedded in review evidence.
- Strix run `28015621232` reported `GitHub Actions pull_request_target with PR Code Execution` against `.github/workflows/opencode-review.yml`. OpenCode Review is now `workflow_dispatch`-only, and the scheduler dispatches same-head Strix before same-head OpenCode. This follows GitHub's secure-use guidance to avoid `pull_request_target` with untrusted PR checkout/execution: https://docs.github.com/en/actions/reference/security/secure-use and GitHub Security Lab's "Preventing pwn requests": https://securitylab.github.com/resources/github-actions-preventing-pwn-requests/.
- OpenCode run `28017920517` failed without posting a PR review because every model attempt failed to produce a valid control block; the primary `github-models/openai/gpt-5` error was `Request body too large for gpt-5 model. Max size: 4000 tokens.` The prompt now requires reading `bounded-review-evidence.md` instead of inlining `bounded-review-evidence-excerpt.md`.
- PR #37 head `ce5591e` reproduced the self-modifying workflow hazard: the base-branch `pull_request_target` OpenCode run `28019367683` posted `REQUEST_CHANGES` from skipped coverage evidence, while the same-head manual `coverage-evidence` job in run `28019384032` proved 100% test and docstring coverage. The central policy removes `pull_request_target` from OpenCode review and relies on scheduler-dispatched `workflow_dispatch` evidence for PR-head review.
- OpenCode run `28019384032` also showed a model-output repair gap: DeepSeek V3 returned an `APPROVE` control block but wrote `Coverage: Not applicable` and `Docstring coverage: Not applicable` even though bounded current-head evidence proved both at 100%. The normalizer now reads the last concrete verification label after evidence-based repair, so an appended repair summary can replace earlier invalid model labels without accepting missing coverage.
- Strix run `28022323798` caught that the first label repair changed normalizer parsing too narrowly: inline approval summaries in `test_strix_quick_gate.sh` no longer normalized. Label parsing now accepts inline verification labels while excluding the `Coverage:` suffix inside `Docstring coverage:`, preserving both inline transcript controls and appended evidence repair.
- PR #37 same-head manual Strix run `28023392848` succeeded for head `07a6b76`, but the concurrently dispatched same-head manual OpenCode run `28023401894` spent its early lifetime waiting in `Prepare bounded OpenCode review evidence`. That exposed a scheduler-level resource issue: dispatching Strix and OpenCode together can turn OpenCode into a long poller whenever Strix is queued or slow. The scheduler now serializes the process: first dispatch Strix, then wait for a later scheduler pass to dispatch OpenCode after Strix evidence is complete.
- The base-branch automatic OpenCode run `28025023007` still posted a current-head `CHANGES_REQUESTED` review before cancellation on head `1d05f52`, even though that automatic trigger is removed by this PR. The scheduler previously treated any current-head OpenCode `CHANGES_REQUESTED` as permanent. It now reads the latest OpenCode review on the current head, so a later same-head OpenCode approval can supersede an earlier false negative from the same reviewer.
- `clearfolio` PR #13 and `codec-carver` PR #98 are opened as thin rollouts. Their scheduler workflows now pin `scripts/ci/pr_review_merge_scheduler.py` to central commit `7be2d99` and verify SHA-256 `f954b62efa4ad60964a65501d777cb4ba26f1ac5746c2d11406d610a5ab695f6` before running the script self-test and inspecting their own PR queues. `codec-carver` PR #98 also deletes the legacy OpenCode app-token merge workflow.
- `clearfolio` PR #13 first failed Strix run `28027843973` because `opencode.jsonc` was missing. Commit `38e9a82` added the central `opencode.jsonc`, but Strix runs `28028155386`, `28030126946`, and `28030438259` still failed because clearfolio's trusted-base `strix.yml` did not copy `PR_HEAD_SHA:opencode.jsonc` into the trusted workspace. Commit `2618c41` adds the PR-head `opencode.jsonc` and scheduler-policy materialization to `strix.yml`; PR-target Strix run `28030872994` and same-head manual Strix run `28030912898` were still in progress or queued at the 2026-06-23 22:48 KST snapshot.
- `codec-carver` PR #98 already has base `opencode.jsonc`. PR #98 now pins the central scheduler instead of downloading from `main`; same-head Strix run `28030439830` and OpenCode runs `28030438605`/`28030439065` were still in progress at the 2026-06-23 22:48 KST snapshot.
- `.github` PR #38 exposed two central gaps after PR #37 merged: the `review_dispatch` reason lost the `same-head Strix and OpenCode dispatched` contract string, and `failed_status_checks()` treated failed PR-target Strix check runs as blockers even when a later manual `strix` status could supersede them. Commit `7be2d99` restores the reason string, materializes PR-head scheduler policy as non-executed data for Strix self-test, and ignores stale Strix check-run failures when the same head has a successful `strix` status context. Manual Strix run `28030448032` had passed self-test and was still running `Run Strix (quick)` at the 2026-06-23 22:48 KST snapshot.
