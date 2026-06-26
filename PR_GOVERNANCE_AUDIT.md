# PR Governance Audit

Live check: 2026-06-26 KST, GitHub API via `gh` as `seonghobae`.

## Canonical Policy

OpenCode decides; GitHub Actions mutates.

- The canonical implementation belongs in `ContextualWisdomLab/.github`.
  Repository-local copies of the scheduler, OpenCode review workflow, Strix
  gate, or helper scripts are drift sources, not repo-specific contracts.
- Target repositories should contain at most thin workflow callers, or no caller
  at all when an organization required-workflow/ruleset mechanism can provide
  the trigger. Thick downstream sync PRs are an anti-pattern unless they are a
  temporary rollback bridge.
- `fork` versus `non-fork` is not the rollout boundary. Central governance
  applies to every target repository that opts into the organization contract.
  Runtime decisions classify the PR head capability instead: observable,
  reviewable, updateable, auto-mergeable, and mergeable. External heads may be
  fully reviewable while remaining non-mutable by the scheduler credential.
  The same rule applies to repository onboarding: a public fork can be governed
  by the same reusable workflow if it deliberately opts in, while a non-fork
  PR head can still be non-mutable at runtime. The scheduler must decide from
  observed PR permissions and current-head evidence, not from the repository's
  `fork` flag alone.
- GitHub workflow templates can help create thin callers, but templates are
  scaffolding, not centralized execution. Reusable workflows (`workflow_call`)
  centralize implementation while a caller or required-workflow trigger supplies
  the target repository event and token context.
- Live organization state at the 2026-06-26 KST check: Actions are enabled for
  all repositories, all actions and reusable workflows are allowed, and the
  organization rulesets API returned no organization-level rulesets. That means
  central rollout should start with reusable workflows plus thin callers, then
  replace callers with organization required workflows only after the feature is
  verified live for this plan/account.
- OpenCode may return only a decision: `UPDATE_BRANCH`, `WAIT`, `REQUEST_CHANGES`, or `NO_ACTION`.
- GitHub Actions updates only mutable PR heads with `expected_head_sha` after
  current-head failed checks have been ruled out. Same-repository heads are
  normally mutable; external heads are attempted only when GitHub exposes a
  maintainer-writable head path, and otherwise receive explicit update
  guidance instead of being skipped.
- The GitHub REST permission surfaces are split: `update-branch` uses Pull
  requests write permission, while merge uses Contents write permission
  (GitHub REST pull request endpoint docs:
  https://docs.github.com/en/rest/pulls/pulls#update-a-pull-request-branch and
  https://docs.github.com/en/rest/pulls/pulls#merge-a-pull-request,
  2026-06-25 check). Do not widen `contents` just to support `update-branch`.
- Old approvals and old checks are not merge evidence after a head SHA changes.
- OpenCode review evidence must be internally same-head as well as GitHub-attached same-head. If the review body includes `Gate evidence` with `Head SHA: <sha>`, that SHA must match the PR current `headRefOid`; otherwise the review is stale evidence even when GitHub attaches the review to the current commit.
- Merge uses one path: current-head OpenCode approval, no active unresolved review threads, required checks green or native auto-merge waiting on them, mergeable head, and no policy blocker. GitHub `Outdated` review threads are obsolete diff conversations; the scheduler resolves them before counting active unresolved review blockers.
- Prefer `gh pr merge --auto --merge --match-head-commit <head>` when native auto-merge is enabled.
- Use direct `gh pr merge --merge --match-head-commit <head>` only when the repo policy already allows immediate merge.
- Scheduler merge behavior is explicit: `merge_mode=auto` uses native GitHub
  auto-merge, `merge_mode=direct` performs an immediate guarded merge with the
  workflow `GITHUB_TOKEN`, and `merge_mode=disabled` reports the approved head
  without mutating it. Direct merge requires `CLEAN` mergeability and is a
  repository policy choice, not a fallback for missing evidence.
- OpenCode app-token merges are deprecated; keep app tokens for review publication, not mechanical branch mutation.
- OpenCode approval publication must be bounded. Peer GitHub Checks can be awaited, but the approval step itself must time out instead of running for hours; the current central limit is a 45 minute approval step with 81 peer-check probes at 30 seconds.
- Tool failures are not source findings. Model failure, API transient, update-branch `422/403`, fork/write-permission failure, conflict, failed checks, and stale review state must be reported as distinct scheduler outcomes. A failed current-head check blocks `UPDATE_BRANCH`; the scheduler must not use a branch update as a way to hide or bypass failed evidence.
- Developer experience and user experience are separate review surfaces. Reviews must adopt helpful sibling-repo automation, review, setup, documentation, and product-flow patterns when they reduce friction, and flag noisy automation, false failures, misleading status, repeated waiting, or URL-only diagnostics as experience defects instead of treating them as neutral implementation detail.
- When OpenCode publishes `REQUEST_CHANGES`, the same review body and attempted
  inline-comment payload must also be emitted to the GitHub Actions log and job
  summary. Humans and later agents should not have to infer the review content
  from a URL-only failure or a missing PR-side publication.

## Non-Actionable Findings Ban

The review surface must not publish a `Findings` block that merely says the
reviewer failed to map evidence. Generic "I could not map the failed check"
phrasing is an internal diagnosis failure, not a code-review finding. If
OpenCode or the deterministic fallback helper cannot map an active failed check
to a concrete local file, positive line number, failed log phrase, observable
impact, fix direction, regression command, and source-backed suggested diff,
the workflow must leave the PR review unchanged and expose the state as a
rerunnable tool outcome. It may not convert missing evidence into
`REQUEST_CHANGES`, and it may not ask the human reviewer to perform the mapping
inside the Findings section.

Acceptable failed-check findings are narrow: each finding must identify the
failed check label, cite the exact log or annotation phrase, point to an actual
changed or relevant local source line, explain why that line causes the failure,
and provide a minimal fix plus a verification target. Cancelled checks,
provider budget/rate-limit errors, missing artifacts, and GitHub permission
failures are external execution states unless current-head source evidence ties
them to a local defect.

## Live Repository Inventory

Live generated: 2026-06-26 KST via GitHub REST/GraphQL APIs. PR #28 post-merge refresh: 2026-06-23 16:05 KST. PR #37 post-merge refresh: 2026-06-23 21:50 KST. clearfolio PR #13 post-merge refresh: 2026-06-24 04:48 KST. Non-actionable Findings refresh: 2026-06-25 KST. PR #58, #65, #66, #68, and #71 post-merge refreshes: 2026-06-25 to 2026-06-26 KST. The current organization target inventory contains 12 public non-fork repositories, and the public fork inventory contains 6 repositories. `VibeSec` was not in that target set, and `appguardrail` was.

Continuation snapshot: 2026-06-26 09:45 KST (`2026-06-26T00:45:40Z`). Every
public repository can be observed under the same governance scan, but write
actions remain PR-head capability checks.

| Bucket | Repositories | Scheduler implication |
|---|---|---|
| Public target repos with OpenCode, Strix, and scheduler present | `.github`, `appguardrail`, `clearfolio`, `codec-carver`, `ContextualWisdomLab.github.io`, `naruon`, `newsdom-api`, `pg-erd-cloud`, `scopeweave` | Convert thick scheduler copies to thin callers after the central reusable workflow supports the needed merge mode. |
| Public target repos missing Strix | `bandscope`, `hyosung-itx-slogan-brief` | Do not blindly enable `trigger_reviews`; first add Strix or call the scheduler with review dispatch disabled. |
| Public target repos missing all governance workflows | `contextual-orchestrator` | Decide whether it opts in or remains unmanaged. |
| Public forks | `argos`, `html4tree`, `nonnest2`, `seedream_evasepic`, `vooster`, `vooster-v2-mvp` | Fork status is not a categorical exclusion; onboarding is an explicit repository decision, and PR mutation remains capability-gated per head. |

| Repo | Flow | Default | Auto | Rulesets | Required checks | Stale dismissal | Open PRs | Workflows | Recent merged actor |
|---|---:|---:|---:|---|---|---:|---:|---|---|
| `ContextualWisdomLab/.github` | GitHub Flow | `main` | on | `Lock default branch` | none | ruleset true | 27 | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | mixed: `seonghobae`, `github-actions` |
| `ContextualWisdomLab/bandscope` | Git Flow | `develop` | on | `Lock default branch` | `CodeQL`, `ci / build-and-test`, `dependency-review`, `gate / build / macos`, `gate / build / windows`, `release-preflight`, `sbom`, `security-audit`, `trivy-fs-scan` | ruleset true; classic false | 79 | OpenCode Review; PR Review Merge Scheduler | mixed: `seonghobae`, `github-actions` |
| `ContextualWisdomLab/clearfolio` | GitHub Flow | `main` | off | `PR` | none | ruleset false | 13 | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | #13 `seonghobae`; #9 `seonghobae`; #8 `seonghobae` |
| `ContextualWisdomLab/codec-carver` | GitHub Flow | `main` | on | `Lock default branch` | none | ruleset true | 9 | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | mixed: `github-actions`, `opencode-agent`, `seonghobae` |
| `ContextualWisdomLab/contextual-orchestrator` | GitHub Flow | `main` | off | none | none | none | 0 | none matched | none |
| `ContextualWisdomLab/ContextualWisdomLab.github.io` | GitHub Flow | `main` | on | `Lock default branch` | none | ruleset true | 9 | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | mixed: `github-actions`, `seonghobae` |
| `ContextualWisdomLab/hyosung-itx-slogan-brief` | GitHub Flow | `main` | off | `Do not delete any branches` | none | none | 0 | OpenCode Review; PR Review Merge Scheduler | #3 `seonghobae`; #2 `seonghobae`; #1 `seonghobae` |
| `ContextualWisdomLab/naruon` | Git Flow | `develop` | on | `Lock default branch`, `PR` | `opencode-review`, `strix` | ruleset true; classic true | 3 | OpenCode Review; PR Governance; PR Review Merge Scheduler; Strix Gate Self-Test; Strix Security Scan | `seonghobae` |
| `ContextualWisdomLab/newsdom-api` | Git Flow | `develop` | on | `Lock default branch`, `mirror-classic-protection-main-develop` | `codeql (python, actions)`, `dependency-review`, `pytest`, `quality-gate`, `scorecard` | ruleset true | 0 | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | `seonghobae` |
| `ContextualWisdomLab/pg-erd-cloud` | GitHub Flow | `main` | on | `Lock default branch` | none | ruleset true | 12 | OpenCode Review; PR Review Autofix; PR Review Fix Scheduler; PR Review Merge Scheduler; Strix Security Scan | mixed: `github-actions`, `seonghobae` |
| `ContextualWisdomLab/scopeweave` | Git Flow | `develop` | on | `Lock default branch` | none | ruleset true | 8 | OpenCode Review; PR Review Merge Scheduler; Strix Gate Self-Test; Strix Security Scan | `seonghobae` |
| `ContextualWisdomLab/appguardrail` | Git Flow | `develop` | on | `Lock default branch`, `PR` | none | ruleset true | 0 | OpenCode Review; PR Review Merge Scheduler; Strix Security Scan | `seonghobae` |

## Current Gaps By Repo

| Repo | Gap |
|---|---|
| `.github` | PR #37, #38, #41, #42, #49, #58, #65, #66, #68, and #71 are merged. PR #49 is the central proof that generic failed-check deflections are rejected before publication. PR #58 extends that contract so pending checks, check-rollup lookup failures, failed-check diagnosis gaps, conflict repair guidance, update-branch explanations, and scheduler decisions stay tool states or Actions Summary output instead of becoming user-facing Findings. PR #65 adds explicit conflict guidance and workflow-token `update-branch`; PR #66 requires exact current-head approval by commit OID; PR #68 adds REST mergeability because GraphQL `mergeStateStatus` stayed stale after live updates; PR #71 makes the scheduler callable as canonical organization workflow code instead of another repo-local copy. |
| `bandscope` | Required checks are repo-specific and broad; keep GitHub native auto-merge as the check interpreter. PR #459 merged the REST mergeability guard downstream. Scheduler run `28192186833` proved two current contracts: PR #450 emitted concrete conflict repair guidance instead of retrying `update-branch`, and PR #451/#446 requested `update-branch` with the workflow `GITHUB_TOKEN`, producing new heads authored by `github-actions[bot]`. That run also exposed a post-update `ACTION_REQUIRED` state with no jobs, so the scheduler must report workflow approval/policy wait rather than a source failure when it recurs. Follow-up PR #460 was closed because it copied the central scheduler into `bandscope` and would preserve exactly the repo-local drift this rollout should remove. |
| `clearfolio` | PR #13 is merged at `4bc17c6` after same-head manual Strix run `28051319530`, same-head manual OpenCode run `28051665082`, unresolved review threads `0`, and guarded merge against head `5fe1791`. Auto-merge remains off, so direct guarded merge is the repo path. |
| `codec-carver` | PR #98 replaced the legacy scheduler with the central GitHub Actions path. Keep #94 as the historical negative sample because it used `opencode-agent` as a merge actor. |
| `contextual-orchestrator` | No matching rulesets or review workflows; either opt in deliberately or mark unmanaged. |
| `hyosung-itx-slogan-brief` | Public organization repo discovered in the 2026-06-25 13:46 KST refresh. It has OpenCode Review and PR Review Merge Scheduler but auto-merge is off and the only ruleset prevents branch deletion, so it should either stay as a lightweight GitHub Flow repo or explicitly opt into the default-branch lock contract. |
| `naruon` | Canonical strict check source. PR #756 synced the central scheduler into `naruon`; its first head proved that widening `GITHUB_TOKEN` permissions to solve DX creates Scorecard and governance failures, so the merged rollout keeps minimal token permissions and defaults risky review-dispatch/auto-merge paths off. PR #721 remains the useful historical fixture for `BEHIND` handling: central dry-run selected `update_branch`, while the older repo-local workflow treated it as `wait`. Current PR #760 is clean, approved, and green on head `57a2f8e4`, so it is a merge-readiness sample; current dry-run with auto-merge disabled reports `wait`, as expected for the low-privilege scheduler profile. |
| `newsdom-api` | Ruleset-required checks must stay GitHub-interpreted. PR #207 has merged, so it is no longer an update-branch proof candidate. The remaining open PRs #187, #203, #205, and #206 currently block because the current head has no OpenCode approval. |
| `pg-erd-cloud` | Good GitHub Actions merge samples; keep autofix workflows repo-local. |
| `scopeweave` | PR #127 is the current representative trace. Dry-run `28147098767` selected `auto_merge`, but live run `28147157319` failed with `GraphQL: Resource not accessible by integration (mergePullRequest)` because merge through GitHub Actions requires a contents-write mutation surface. Commit `6601953` proved the tempting fix, but Scorecard immediately opened a Token-Permissions review thread against job-level `contents: write`; follow-up commit `c5c5530` restores `contents: read` and keeps update-branch on the lower-privilege PR-write path. Current head `c5c5530` is clean, approved, and green; it remains unmerged because Actions-based merge is an explicit repo policy exception, not the default rollout. |
| `appguardrail` | Public organization repo discovered in the 2026-06-26 refresh. It follows Git Flow on `develop`, has the central review/merge workflow names, and has no open PRs at the snapshot, so it is a clean onboarding target for the central contract rather than a proof fixture. |

## Representative Evidence

| Repo | Live evidence | Adopt | Reject |
|---|---|---|---|
| `naruon` | `develop`, strict required checks `opencode-review` and `strix`, stale review dismissal enabled. Open PRs show `BEHIND`, `DIRTY`, and `CHANGES_REQUESTED` cases. | Strict current-head evidence and stale-dismissal awareness. | Treating `BEHIND` as merge-ready. |
| `bandscope` | Workflow dry-run `28134181171` used the repo-local scheduler and reported `PR #367: wait: current head is approved; auto-merge already enabled`, while the central scheduler dry-run selected `update_branch` for the same `BEHIND` + current-head-approved class. PR #459 is the downstream REST-mergeability rollout. Run `28192186833` then produced conflict guidance for #450 and `github-actions[bot]` branch updates for #451/#446, but those updated heads exposed `ACTION_REQUIRED` check runs with no jobs. | Keep broad repo-specific required checks delegated to GitHub, update outdated mutable PR heads before relying on native auto-merge, and treat `ACTION_REQUIRED` as workflow approval/policy wait. | Assuming an enabled auto-merge request means the PR branch is current enough to merge, converting missing evidence into a PR Finding, or treating `ACTION_REQUIRED` as a failed source check. |
| `.github` | PR #28 head `811446d` reached current-head approval after manual Strix run `28007326148` published a successful `strix` status and manual OpenCode run `28008174977` approved the same head; it was merged by `seonghobae` with merge commit `a025be1`. PR #49 then merged the explicit ban on generic failed-check deflections, and PR #58 removes remaining fallback/pending/check-lookup paths that could turn review-tool states into PR review Findings. | Same-head manual evidence for self-modifying trusted workflow changes, current-head OpenCode approval, unresolved thread check, `--match-head-commit` guarded merge, and non-actionable Findings rejection. | Treating stale PR-target failure logs as merge blockers after newer same-head evidence exists, or posting an evidence-mapping failure as a user-facing Finding. |
| `pg-erd-cloud` | Recent PRs #236, #237, #239 were merged by `app/github-actions`. | GitHub Actions as mechanical merge actor with head guard. | Human-only queue draining. |
| `codec-carver` | Recent PR #94 was merged by `app/opencode-agent`, and the repo still has legacy `Scheduled PR Review Merge`. | Native auto-merge path for current-head approved PRs. | OpenCode app as merge actor. |
| `appguardrail` | Current public organization repo with default `develop`, central workflow names, and no open PRs at snapshot time. | Use as a clean onboarding/control repo after central changes stabilize. | Treating zero open PRs as proof that the workflow behavior is already correct. |

## DX/UX Transfer Decisions

Developer experience means the maintainer, reviewer, CI operator, and future
contributor experience. User experience means the product user, documentation
reader, PR reader, and status-check reader experience. PR review must evaluate
both separately; a change can improve one while harming the other.

| Repo | Borrow because it helps DX/UX | Improve because it creates friction | Central action |
|---|---|---|---|
| `.github` | Same-head manual evidence and `--match-head-commit` make self-modifying workflow changes reviewable without pretending stale base-branch checks are current. | Stale `pull_request_target` failures, long polling review runs, and cancelled helper checks can become misleading review noise. | Serialize Strix before OpenCode, bound approval runtime, and require failed-check explanations instead of URL-only comments. |
| `naruon` | Strict required checks, stale review dismissal, changed-file Mermaid flow DAGs, and current-head evidence make review evidence easier to audit. | The repo-local scheduler is stale: it has no update-branch path, no Strix-before-OpenCode sequencing, and no failed-check interpretation from the central script. Run `28073490721` also showed that an auto-merge permission failure can stop the whole queue before later PRs are inspected. PR #756 additionally showed that broadening workflow permissions is a tempting DX shortcut, but it degrades review trust and triggers Scorecard/governance failures. | Move the implementation contract back to `.github` reusable workflows, keep only a thin caller or required-workflow trigger in `naruon`, re-review every updated head, require an exact changed-file evidence path plus a Change Flow DAG before approval, keep `actions: read`/`contents: read` unless a separate privileged workflow is deliberately introduced, and record action failures per PR instead of aborting the scan. |
| `pg-erd-cloud` | GitHub Actions bot merges with head guards give a clear mechanical actor for merges. | Repo-local autofix workflows are useful there, but centralizing autofix would widen mutation scope too far. | Keep GitHub Actions as the merge actor and leave autofix workflows repo-local. |
| `appguardrail` | Security-review subject matter makes it a useful place to verify that review automation distinguishes policy failure, tool failure, and source-code failure. | With no open PRs in the snapshot, it cannot yet prove update-branch or merge behavior. | Onboard central scheduler changes deliberately, then use the next real PR as a low-noise policy-vs-source review fixture. |
| `bandscope` | Broad required checks encode repo-specific release, build, SBOM, and security expectations. | Copying the central scheduler into this repo turns one canonical contract into another repo-local drift surface. | Let GitHub native auto-merge and rulesets interpret required checks, and replace thick local governance files with a thin caller or organization required workflow. |
| `newsdom-api` | Required quality gates and security checks give API changes stronger release evidence. | Central review comments that only point at failing check URLs do not help an API maintainer fix the failure. | Require failed-check root cause, source location when available, fix direction, and rerun command. |
| `scopeweave` | Strix self-test and the central scheduler are useful rollout fixtures. Live scheduler run `28147157319` proved `action_error` is reported per PR instead of aborting the queue, and follow-up `c5c5530` shows the safer rollback when Scorecard rejects a broad token. | The scheduler could identify #127 as merge-ready, but enabling GitHub Actions merge by adding job-level `contents: write` triggered a Scorecard Token-Permissions thread. | Keep update-branch on `pull-requests: write` with `contents: read`; keep OpenCode read-only; require an explicit repo-level exception before letting the scheduler perform merge or auto-merge with `contents: write`. |
| `clearfolio` | Direct guarded merge works while auto-merge is intentionally off. | Treating it like an auto-merge repo would create confusing expectations. | Use immediate guarded merge only after same-head evidence, unresolved-thread check, and head guard pass. |
| `codec-carver` | Existing native merge behavior can be retained once current-head evidence is clean. | Legacy OpenCode app-token merge creates a second mechanical actor and weakens audit consistency. | Replace legacy scheduled merge with the central GitHub Actions scheduler. |
| `ContextualWisdomLab.github.io` | Site and documentation changes make reader-facing UX review concrete. | Review comments that say only that a check failed do not help the site reader or maintainer understand the issue. | Treat documentation clarity, homepage behavior, and status-check explanations as UX surfaces. |
| `hyosung-itx-slogan-brief` | The repo has the central review/merge workflow names without heavier required checks, which makes it a lightweight GitHub Flow fixture. | It lacks the default-branch lock/stale-dismissal policy used by most organization repos. | Leave unmanaged only if that is intentional; otherwise add the standard default-branch lock before relying on autonomous merge. |
| `contextual-orchestrator` | No central pattern is present yet, so it can be onboarded deliberately instead of accidentally. | Silent unmanaged status is easy to miss in organization-level governance. | Either opt it into the central workflows or explicitly mark it unmanaged. |

## Current Scheduler Contract

The checked-in scheduler already does the minimal central path:

- skips only draft PRs and PRs whose base branch is outside the configured
  scheduler target branch;
- keeps external-head PRs in the same observation and review pipeline, then
  gates only the write actions by PR head mutation capability;
- blocks UI `Conflicting`, API `DIRTY`, or API `CONFLICTING` with repair guidance that names the base branch, head branch, merge/rebase direction, conflict-marker cleanup, focused checks, same-branch push, and a compact `gh pr checkout` / `git fetch` / merge-or-rebase / `git status --short` command path; it explicitly does not retry `update-branch` for conflicted PRs because GitHub cannot choose the correct conflict resolution;
- resolves GitHub `Outdated` unresolved review threads through `resolveReviewThread` before active blocker checks, using the scheduler workflow `GITHUB_TOKEN` inside GitHub Actions; dry-runs report the cleanup as `notes` without mutating the PR;
- blocks active, non-outdated unresolved review threads;
- blocks current-head OpenCode `CHANGES_REQUESTED`;
- blocks current-head failed check runs or status contexts before enabling auto-merge;
- waits on `ACTION_REQUIRED` check runs as workflow approval or repository-policy states, not as source-code failures; failed checks still take precedence for current-head-approved PRs, so `ACTION_REQUIRED` cannot mask a real failed `strix`, lint, build, or required-check result;
- rejects OpenCode reviews whose GitHub review commit matches the PR head but whose review-body `Gate evidence` names a different `Head SHA`; this prevents stale review evidence from becoming current-head approval by attachment alone;
- updates `BEHIND` only when OpenCode approved the exact current head, no current-head failed check is present, and the PR head is actually mutable by the scheduler credential, using `expected_head_sha` from the scheduler workflow `GITHUB_TOKEN` so the mechanical branch update is performed by `github-actions[bot]` inside GitHub Actions instead of an OpenCode or maintainer-local credential; the script now refuses non-dry-run `update-branch` outside GitHub Actions, and this path needs `pull-requests: write`, not `contents: write`;
- waits with `external_head_update_required` guidance when a current-head-approved external PR head is behind but is not writable by the scheduler credential, instead of treating fork/non-fork as an onboarding exception;
- enables native auto-merge only for current-head OpenCode approval;
- supports explicit merge policy through `merge_mode`: `auto` enables native
  auto-merge, `direct` performs a guarded `gh pr merge --merge
  --match-head-commit <head>` through `github-actions[bot]` for repositories
  that do not use native auto-merge after GitHub reports `CLEAN` mergeability,
  and `disabled` records the approval without mutating the PR;
- dispatches same-head Strix evidence first when the current head has no completed Strix evidence;
- waits while same-head Strix evidence is still running, so OpenCode is not started just to poll a peer check;
- keeps old Strix evidence running instead of cancelling it, but scopes PR Strix concurrency by head SHA so an obsolete scan does not serialize newer current-head evidence;
- dispatches OpenCode only after same-head Strix evidence is complete, including failed Strix evidence that OpenCode must explain from logs.
- records mutation failures as `action_error` for the affected PR and continues scanning later PRs, so a permission failure on one merge/update action does not hide the rest of the queue.
- writes the same per-PR decisions to the GitHub Actions step summary, so conflict repair and update-branch decisions are visible without opening raw logs.
- prints a machine-readable `pr-review-merge-scheduler/v2` JSON contract with every inspected PR, the scheduler action, the bounded decision value (`UPDATE_BRANCH`, `WAIT`, `REQUEST_CHANGES`, or `NO_ACTION`), optional cleanup `notes`, and structured `guidance` for states that need action: `merge_conflict_repair` includes the base/head branches, repair steps, and merge-or-rebase commands; `github_actions_update_branch` names `github-actions[bot]`, the workflow `GITHUB_TOKEN`, `pull-requests: write`, `expected_head_sha`, and the new-head evidence required before merge; `github_actions_direct_merge` names `github-actions[bot]`, the workflow `GITHUB_TOKEN`, `contents: write`, `gh pr merge --match-head-commit`, and post-merge evidence; `workflow_action_required` names the affected check runs and requires GitHub Actions approval or policy unblock before rerunning the scheduler.
- caps each GraphQL PR page at 25 nodes, so large queues can be scanned without hitting GitHub's query resource limit.
- excludes OpenCode Review's own `opencode-review` check from peer failed-check evidence, so a cancelled or stale OpenCode run cannot become a source-code `REQUEST_CHANGES` review against the same head.

Small proof run:

```text
$ python3 scripts/ci/pr_review_merge_scheduler.py --self-test
self-test passed

$ python3 scripts/ci/pr_review_merge_scheduler.py --repo ContextualWisdomLab/scopeweave --base-branch develop --project-flow git-flow --dry-run --max-prs 40 --no-trigger-reviews --no-enable-auto-merge
PR #119: block: merge conflict: DIRTY; base=develop, head=bolt/perf-format-number-1301647661105713430; run `gh pr checkout 119`, `git fetch origin develop`, then `git merge --no-ff origin/develop` or `git rebase origin/develop`; use `git status --short` to find conflicted files, resolve conflict markers in the PR branch, rerun focused checks, and push the same bolt/perf-format-number-1301647661105713430 branch (use `git push --force-with-lease` only if rebased)
...
PR #127: wait: current head is approved; auto-merge disabled by scheduler inputs
{"base_branch": "develop", "counts": {"block": 6, "wait": 1}, "decisions": [...], "dry_run": true, "inspected": 7, "project_flow": "git-flow", "schema_version": "pr-review-merge-scheduler/v2"}

$ python3 scripts/ci/pr_review_merge_scheduler.py --repo ContextualWisdomLab/.github --base-branch main --project-flow github-flow --dry-run --max-prs 40 --no-trigger-reviews --no-enable-auto-merge
PR #44: wait: current head is approved; auto-merge already enabled
...
{"base_branch": "main", "counts": {"block": 24, "wait": 1}, "decisions": [...], "dry_run": true, "inspected": 25, "project_flow": "github-flow", "schema_version": "pr-review-merge-scheduler/v2"}

$ python3 scripts/ci/pr_review_merge_scheduler.py --repo ContextualWisdomLab/bandscope --base-branch develop --project-flow git-flow --dry-run --max-prs 40 --no-trigger-reviews --no-enable-auto-merge
PR #378: wait: OpenCode review is already in progress
PR #381: wait: OpenCode review is already in progress
...
{"base_branch": "develop", "counts": {"block": 38, "wait": 2}, "decisions": [...], "dry_run": true, "inspected": 40, "project_flow": "git-flow", "schema_version": "pr-review-merge-scheduler/v2"}
```

## Rollout List

1. Stop thick per-repository scheduler/OpenCode/Strix copies. `bandscope` PR
   #460 is closed as the negative example of the wrong rollout shape.
2. Add or preserve canonical workflows in `ContextualWisdomLab/.github` and make
   them callable through `workflow_call` or an organization required-workflow
   mechanism after live feature verification.
3. For repositories that need PR-event triggers, keep only thin callers that
   pass PR number, base ref/SHA, head ref/SHA, target flow, and inherited
   secrets/permissions into `.github`.
4. Treat fork and non-fork repositories uniformly for onboarding. At runtime,
   classify only the PR head mutation capability: observable/reviewable,
   updateable, auto-mergeable, or mergeable.
5. Keep repo-specific product/build/autofix workflows repo-local only when they
   are not part of the governance contract. `pg-erd-cloud` autofix stays
   repo-local; PR review/merge governance should not.
6. Decide whether `contextual-orchestrator` should join the central governance
   surface; no matching workflows or rulesets were returned.

## Remaining Proof Gaps

- 2026-06-26 KST continuation snapshot: `.github` PR #68 is merged at merge commit `590b4ecb2ac9eac700019a183081309e28d8f25b`; `bandscope` PR #459 is merged at merge commit `a7173e45304d8681f02fdf43e4de5a6b6540bb44`. The live organization target inventory contains 12 public repositories and confirms `appguardrail` is present while `VibeSec` is not in that set.
- `bandscope` scheduler run `28192186833` is the current live fixture. PR #450 produced conflict guidance with `gh pr checkout 450`, `git fetch origin develop`, merge-or-rebase, `git status --short`, same-branch push, and `--force-with-lease` only for rebase. PR #451 and PR #446 were updated through the workflow `GITHUB_TOKEN`; the resulting head commits were authored by `github-actions[bot]`.
- The same `bandscope` run exposed a non-source blocker after the `github-actions[bot]` branch updates: the new-head workflows for PR #451/#446 completed as `ACTION_REQUIRED` with no jobs, and the fork-run approval endpoint returned `This run is not from a fork pull request (HTTP 403)`. The scheduler must therefore report `workflow_action_required` and wait for approval or policy unblock instead of saying `failed check(s)` or posting a code finding when that state appears.
- The 2026-06-26 KST `bandscope` follow-up also exposed a stale-evidence attachment hazard: PR #387, #446, and #451 had OpenCode reviews whose GraphQL `review.commit.oid` matched the current head, while the review body `Gate evidence` named an older `Head SHA`. After the central scheduler added review-body Head SHA validation, the same dry-run classified all 79 inspected `bandscope` PRs as blocked; #387/#446/#451 now report `current head has no OpenCode approval` instead of auto-merge wait.
- `newsdom-api` PR #207 is no longer an update-branch proof candidate because it has merged by `seonghobae`. Future GitHub Actions bot update-branch proof should use a head commit authored by `github-actions[bot]` plus the scheduler run log showing the `update-branch` API call.
- A live current-head review -> same-head manual Strix status bridge -> OpenCode approval -> guarded merge trace has been completed on `.github` PR #28.
- No live outdated -> update-branch -> new-head review -> merge/auto-merge trace has been completed yet. `bandscope` PR #459 is the merged downstream corrective rollout for REST mergeability; PR #450 is now a conflict-guidance fixture, not a merge/update proof candidate. The update-branch leg has multiple partial proofs: older scheduler run `28139266598` updated PR #378 with a `github-actions[bot]` head, and newer run `28192186833` updated PR #451/#446 with `github-actions[bot]` heads.
- `bandscope` PR #378 still needs the new-head review/check/merge leg before the full outdated -> update-branch -> new-head review -> merge/auto-merge trace can be closed. At the 15:12 KST refresh, PR #378 is `BEHIND`, has an auto-merge request enabled by `app/github-actions`, and is waiting on in-progress OpenCode plus queued required checks.
- `scopeweave` PR #127 now proves the current-head approval/check -> scheduler decision -> action-error leg: dry-run `28147098767` selected `auto_merge`, and live run `28147157319` reported `action_error` for `mergePullRequest` instead of posting a false code finding or aborting earlier PR decisions. Commit `6601953` showed why blindly adding `contents: write` is not an acceptable universal fix: Scorecard raised an unresolved Token-Permissions thread on the new head. Commit `c5c5530` restores the safer pattern: lower-privilege update-branch by GitHub Actions, with merge through Actions only where the repo deliberately accepts the contents-write exception. The current PR #127 head is merge-ready by review/check state but remains intentionally unmerged by the low-privilege scheduler policy.
- `bandscope` also proved the large-queue scan risk: `max_prs=120` initially failed with `Resource limits for this query exceeded` while reading 80 open PRs. After reducing the GraphQL page size to 25, the same dry-run scanned all 80 open PRs and returned `{"block": 67, "update_branch": 1, "wait": 12}`, including PR #378 as `update_branch` and PR #404 as a conflict block with repair guidance.
- `newsdom-api` no longer has a smaller current update-branch proof candidate in the 15:12 KST dry-run. PRs #187, #203, #205, and #206 all block before update because the current head has no OpenCode approval.
- `.github` PR #58 exposed that a cancelled manual Strix run can keep its manual status publisher queued and delay the next same-PR Strix run. PR #58 now skips that publisher when the workflow is cancelled, scopes Strix PR concurrency by head SHA so obsolete scans do not serialize newer evidence, and requires conflict reviews to include a concrete `gh pr checkout` / `git fetch` / merge-or-rebase / `git status --short` repair path.
- PR #721 in `naruon` remains the historical fixture for this proof: head `b683deaf8b4761399321799279f58d884db57141`, current-head OpenCode approval `4558310923`, unresolved review threads `0`, and `mergeStateStatus=BEHIND`. Central `.github` dry-run selected `update_branch`, but `naruon` workflow run `28073586594` used the then-stale repo-local scheduler and did not update it. PR #756 has since rolled the central scheduler into `naruon`, so the next proof must use a fresh current-head outdated PR instead of reusing stale evidence from #721.
- `naruon` workflow run `28073490721` failed at `gh pr merge 694 --auto --merge --match-head-commit 76416321742af4c8dcd0f96927f64b7548d66fd8` with `GraphQL: Resource not accessible by integration (enablePullRequestAutoMerge)`. This is a DX/governance action failure, not a source-code finding, and the scheduler now records it per PR instead of aborting the scan.
- `naruon` PR #756 completed the repo-local rollout for the scheduler contract. Its initial head failed backend governance and Scorecard because `actions: write`/`contents: write` were broader than the repo policy allows; the amended and merged head restores minimal `GITHUB_TOKEN` permissions, keeps `trigger_reviews` and `enable_auto_merge` defaulted off, keeps `update_branches` defaulted on, and still dry-runs PR #694/#721 as `update_branch`.
- `update-branch` `422/403` now has a safe fixture: unit tests simulate both permission-denied and stale `expected_head_sha` failures, assert they become `action_error`, and assert later PRs are still inspected. A real live `422/403` case is still useful as operational evidence, but it is no longer missing from the decision contract test surface.
- `bandscope` PR #378 exposed a self-referential failed-check loop after manual retry run `28155083916`: the retry run succeeded and approved step execution, but the check rollup still contained the cancelled older `OpenCode Review/opencode-review` run `28152862698`, so OpenCode posted current-head `CHANGES_REQUESTED` review `4569063977` with the banned generic `No deterministic missing-string markers...` text. The collector now excludes OpenCode's own check by check name and by both actual (`OpenCode Review`) and legacy (`OpenCode PR Review`) workflow names before failed-check fallback evidence is built.
- Public repo drift is real, not hypothetical: only `.github` matched the central scheduler/workflow byte-for-byte in the 2026-06-26 scan. Some drift is policy-specific and should not be overwritten blindly, but `bandscope` had behaviorally unsafe drift and now has PR #459 merged downstream.
- The previous drift response still over-indexed on copying. `bandscope` PR
  #460 proved the correction: even when the copied scheduler produced the right
  dry-run result, the PR itself was the wrong operating model because it
  preserved per-repository implementation ownership. The rollout proof must now
  show a target repository invoking `.github` canonical logic without carrying a
  thick local copy.
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
- `clearfolio` PR #13 and `codec-carver` PR #98 were opened as thin rollouts. `clearfolio` PR #13 is now merged at `4bc17c6`; `codec-carver` PR #98 remains the thin rollout that deletes the legacy OpenCode app-token merge workflow.
- `clearfolio` PR #13 first failed Strix run `28027843973` because `opencode.jsonc` was missing. Later current-head proof used manual Strix run `28051319530` and manual OpenCode run `28051665082`; the final approval named the changed review-tooling files and head `5fe1791d48ddcf03dbc365cc6fa407e7cbe70a89` before guarded merge.
- `.github` PR #42 exposed that central approval normalization should not accept generic path-looking evidence when exact current-head changed files are available. The OpenCode workflow now writes `git diff --name-only --find-renames "$PR_MERGE_BASE" "$PR_HEAD_SHA"` to `OPENCODE_CHANGED_FILES_FILE`, gives the isolated review workspace `changed-files.txt`, and the normalizer rejects `APPROVE` unless the approval names one of those exact files.
- `.github` PR #42 same-head OpenCode run `28070438305` exposed a second decode gap: model output reading tolerated invalid UTF-8, but approval-summary repair still read `OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE` as strict UTF-8. DeepSeek produced a repairable control block, then normalization failed on byte `0xea` in bounded evidence. Evidence repair now reads lossy UTF-8 so a damaged transcript byte cannot prevent source-backed normalization.
- `codec-carver` PR #98 already has base `opencode.jsonc`. PR #98 now pins the central scheduler instead of downloading from `main`; same-head Strix run `28030439830` and OpenCode runs `28030438605`/`28030439065` were still in progress at the 2026-06-23 22:48 KST snapshot.
- `.github` PR #38 exposed two central gaps after PR #37 merged: the `review_dispatch` reason lost the `same-head Strix and OpenCode dispatched` contract string, and `failed_status_checks()` treated failed PR-target Strix check runs as blockers even when a later manual `strix` status could supersede them. Commit `7be2d99` restores the reason string, materializes PR-head scheduler policy as non-executed data for Strix self-test, and ignores stale Strix check-run failures when the same head has a successful `strix` status context. Manual Strix run `28030448032` had passed self-test and was still running `Run Strix (quick)` at the 2026-06-23 22:48 KST snapshot.
