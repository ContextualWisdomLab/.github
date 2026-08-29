# ContextualWisdomLab central required workflow rollout

Updated: 2026-08-28 KST

## Decision

Use an organization repository ruleset instead of copying workflow files into each repository.

- Ruleset: `CWL Central required workflows`
- Ruleset ID: `18156473`
- Enforcement: `active`
- Target: branch rules on every repository's default branch (`repository_name.include=["~ALL"]`, `ref_name.include=["~DEFAULT_BRANCH"]`)
- Required workflow source repository: `ContextualWisdomLab/.github`
- Required workflow source repository ID: `1274066402`
- Active required workflow paths:
  - `.github/workflows/close-empty-pr.yml`
  - `.github/workflows/noema-review.yml`
  - `.github/workflows/opencode-review.yml`
  - `.github/workflows/pr-review-merge-scheduler.yml`
  - `.github/workflows/security-scan.yml`
  - `.github/workflows/strix.yml`
  - `.github/workflows/sast-semgrep.yml`
- Required workflow ref: `refs/heads/main`
- Last verified workflow implementation base commit: `050e6d59b0de9e62c8413d5f8f26f4f2f9ebea09` (`#584`)
- Required workflow trigger support: `pull_request`, `pull_request_target`, `push`, `workflow_run`

The required-workflow implementation is current through merged `.github#584`.
The ruleset points at `.github@main`; if live organization ruleset inspection
reports another ref, treat that as operations drift and restore ruleset
`18156473` to the current `main` head.

This keeps Strix security evidence, OpenCode and independent Noema review evidence, and merge/update automation sourced from the central `.github` repository. Target repositories do not need local copies of these workflows for the organization required workflow rule, and new repositories inherit the rule without a repository-name list update.

The central `security-scan.yml` and `sast-semgrep.yml` pull-request triggers are
base-ref agnostic. They therefore also run for stacked pull requests targeting a
feature branch; the organization ruleset's protected-ref scope remains an
independent administrative control and is not weakened by this trigger
coverage.

Stacked pull requests are audited by organization ruleset
`CWL Stacked OpenCode required workflow` (`21732164`) in `evaluate` mode. It
targets every non-default branch and references only
`.github/workflows/opencode-review.yml` from `.github@refs/heads/main`.
Its observed scope is `ref_name.include=["~ALL"]` with
`ref_name.exclude=["~DEFAULT_BRANCH"]`.
Active enforcement over every non-default ref is prohibited: GitHub evaluates
the ref update before a `pull_request_target.synchronize` run can exist for the
new commit, so it rejects both initial branch creation and later review fixes.
Exact-head OpenCode evidence remains a merge requirement enforced by the
normal PR procedure while a target-ref-scoped enforcement design is developed.

## OpenCode required workflow posture

The central `.github/workflows/opencode-review.yml` is now part of the active organization required workflow ruleset.

- Required workflow trigger support: metadata-only `pull_request_target`; the file contains no checkout, PR-head execution, or secret expression
- Stable branch-protection job names: `required-workflow-bootstrap`, `coverage-source-tree`, `coverage-evidence`, and `opencode-review`; these jobs are data-only sentinels, while approval remains a separate current-head PR-review requirement
- Trusted source: `ContextualWisdomLab/.github`
- PR-head handling: authenticated current-head `repository_dispatch` runs `.github/workflows/opencode-review-dispatch.yml` from the protected default branch; that workflow owns metadata validation, bounded coverage, source-as-data inspection, model review, and publication
- Manual target support: the central scheduler sends exact repository, PR, base, and head metadata through `repository_dispatch`; the dispatch workflow rejects an unauthorized actor, an unallowlisted base repository, a malformed head-repository identity, or any live base/head metadata mismatch. A canonical fork head remains reviewable as untrusted source data.
- Model token posture: use the organization `STRIX_GITHUB_MODELS_TOKEN` secret for GitHub Models calls, with `github.token` as the fallback; live workflow evidence showed `github.token` alone can return 403 from `models.github.ai/inference`
- Write posture: OpenCode may create review/comment side effects through the OpenCode app token when available; the workflow token is limited to the same-repository PR context and publication failures remain visible
- Coverage execution posture: PR-controlled package, test, build, R, Rust, and Docker inputs are never executed from `pull_request_target`; the dispatch workflow runs bounded low-privilege coverage only after exact live metadata and scheduler identity validation
- Fork posture: PR heads are fetched through `refs/pull/<number>/head` when direct head-SHA fetch is not available, so review can inspect fork PR source as data without executing it in the trusted workflow context
- Runtime posture: pre-model failed-check evidence waits are capped at about five minutes; the later approval gate rechecks current-head peer checks and extends its bounded wait only while image-validation checks remain pending, logging the reason before approval
- Model-exhaustion posture: command exit codes and deterministic checks cannot synthesize an approval. Exhaustion remains `MODEL_OUTPUT_UNAVAILABLE`; only a prior real-model approval bound to the exact current head can satisfy the review gate after all checks, alerts, and threads are revalidated.
- Adversarial-evidence posture: every probe must cite its exact changed path and positive in-range line in the materialized current-head source tree. Unrelated paths, nonexistent lines, circular claims, and missing observed results fail closed with a concrete rejection reason.

For a bounded current-head retry in one repository, dispatch `merge-scheduler`
to the central repository with `target_repository`, `pr_number`, and the live
`base_branch`. The target must exactly match
`OPENCODE_REPOSITORY_DISPATCH_TARGETS`; the scheduler then re-reads the open PR
and rejects a noncanonical base or head repository name, base mismatch,
malformed head SHA, or changed/closed PR before using cross-repository
credentials. A fork head may pass this read/review boundary, but the scheduler
still excludes it from direct merge, auto-merge, and non-maintainer branch
mutation:

```bash
jq -n '{
  event_type: "merge-scheduler",
  client_payload: {
    target_repository: "ContextualWisdomLab/naruon",
    pr_number: 1179,
    base_branch: "develop",
    trigger_reviews: true,
    review_dispatch_limit: "1",
    enable_auto_merge: false,
    update_branches: false,
    merge_mode: "disabled"
  }
}' | gh api --method POST \
  repos/ContextualWisdomLab/.github/dispatches --input -
```

Use the canonical `full_name` returned by the GitHub repository API. Keep
mutation options disabled for an evidence-only retry; enabling branch updates
or merge behavior is a separate operational decision.

Keep the OpenCode required workflow active only while the central workflow keeps proving current-head coverage, CodeGraph initialization, bounded evidence, model review output, and approval-gate publication on the current head.

## Code scanning required workflow posture

The central `.github/workflows/codeql-pr.yml`, `.github/workflows/scorecard-pr.yml`,
and `.github/workflows/osv-scanner-pr.yml` workflows supply PR-head and merge-preview
code scanning analyses for ruleset `18156473` `code_scanning` (CodeQL, Scorecard,
osv-scanner). They trigger on pull requests to `main`, `master`, and `develop` so
Git Flow repositories on `develop` inherit the same merge gate as GitHub Flow repos.

CodeQL merge preview checks out `refs/pull/<n>/merge` and uploads SARIF with
`sha: pull_request.merge_commit_sha` because the ruleset evaluates that commit,
not the ephemeral merge ref OID.

Repository-local `codeql.yml` push/default-branch scans may remain for branch
history, but PR merge gates should rely on the central `codeql-pr.yml` workflow.

### Repository-local CodeQL inventory (2026-07-04)

Org audit of default-branch workflow files. Repos without any local CodeQL
workflow depend entirely on central `codeql-pr.yml` once ruleset `18156473`
includes that path; they are the most exposed to
`Code scanning is waiting for results from CodeQL` until the ruleset update
lands.

| Repository | Default branch | Local CodeQL workflow | PR trigger | merge_commit_sha SARIF |
| --- | --- | --- | ---: | ---: |
| `aFIPC` | `master` | `codeql.yml` | yes | no |
| `bandscope` | `develop` | `codeql.yml` | yes | no |
| `newsdom-api` | `develop` | `codeql.yml` | yes | no |
| `pg-erd-cloud` | `main` | `codeql.yml`, `codeql-backfill.yml` | yes (`codeql.yml`) | no |
| `xtrmLLMBatchPython` | `develop` | `codeql.yml` | yes | no |
| `naruon` | `develop` | `codeql.yml` | yes (temporary; PR `#916` retires PR trigger) | yes (repo-local interim fix) |
| all other public non-fork org repos | varies | none observed | — | — |

No repository-local PR CodeQL workflow besides `naruon` uploads merge-preview
SARIF on `merge_commit_sha`. Centralizing through `codeql-pr.yml` fixes every
inherited repository in one ruleset change; per-repo deletion of PR triggers is
optional cleanup to avoid duplicate scans.

## Scheduler required workflow posture

The central `.github/workflows/pr-review-merge-scheduler.yml` is now part of the active organization required workflow ruleset.

- Required workflow trigger support: `pull_request_target`
- Stable required check job name: `scan-pr-queue`
- Trusted source: `ContextualWisdomLab/.github`
- PR-event scope: when GitHub invokes the workflow for a PR, the scheduler passes `--pr-number` and inspects only that PR instead of scanning or mutating the whole repository queue
- Token posture: the workflow passes the first available mutation credential in this order: `PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, exchanged OpenCode GitHub App token, then the target repository workflow token. The scheduler reports the non-secret token source and expected actor class in every mutation decision.
- Flow posture: default branches named `main` or `master` are treated as GitHub Flow; default branches named `develop` are treated as Git Flow unless a repository explicitly sets `PROJECT_FLOW`
- Merge posture: the default merge mode is `direct_or_auto`. When a current-head approved PR is same-repository and the scheduler has no failed-check, action-required, unresolved-thread, or conflict blocker, it requests an immediate guarded squash merge with `--match-head-commit`. This includes PRs where native GitHub auto-merge is already enabled; native auto-merge is a fallback queue, not the scheduler's first stop when direct merge is possible.
- Fork posture: fork or external-head PRs remain reviewable, but the scheduler does not direct-merge them and does not enable auto-merge for them. A maintainer must make the final merge decision after same-head OpenCode approval, same-head Strix evidence, required checks, and unresolved-thread checks are clean.
- Branch freshness posture: the scheduler also runs after protected base-branch pushes to `main`, `develop`, or `master`, because those pushes can create the GitHub UI state where reviews are satisfied, auto-merge is enabled, checks are stale or failed, and the PR shows `Update branch` without a PR `synchronize` event.
- Auto-merge posture: `auto_merge_enabled` PR events trigger the scheduler so an already stale branch is refreshed immediately after native auto-merge is turned on instead of waiting for the periodic schedule. If the same PR is already mergeable, the scheduler attempts the guarded direct merge immediately.
- Automation boundary: current-head failed checks and `ACTION_REQUIRED` checks are reported before branch updates, so an update attempt does not hide the concrete reason a PR cannot merge. `update-branch` handles approved `BEHIND` PRs and already queued auto-merge PRs only when there is no current-head failed or action-required check to diagnose first. `DIRTY` or `CONFLICTING` PRs still require author or maintainer conflict resolution guidance; current-head approved conflicts may keep or queue native GitHub auto-merge as a wait state while the conflict is repaired, but the scheduler must not treat queued auto-merge as a conflict resolver.
- Retry posture: before retrying OpenCode, the scheduler force-cancels older active OpenCode runs for the same PR number and a previous head SHA. It does not automatically cancel Strix runs because security evidence should not be silently discarded by force-push churn.

Do not centralize the scheduler by running a `.github` scheduled job against other repositories with the `.github` repository token. That would either fail permission checks or use the wrong mutation actor. The central path is a required workflow executed in each target repository context.

- Heartbeat fallback posture: event-driven target-repository runs stop retrying once their triggering event is consumed, so a PR that becomes mergeable AFTER its last event (approval published after the scheduler pass, merge-preview checks landing late, a temporary base-branch policy blocker clearing) has no later trigger and sits approved-but-unmerged. The `org-queue-sweep` job in the central scheduler workflow closes this gap: it runs every 15 minutes (`*/15 * * * *`) only in `ContextualWisdomLab/.github`, re-runs the same trusted scheduler script against every non-archived organization repository, and merges/updates through the identical guarded contract. Stacked PRs, which do not receive injected required workflows, use a separate bounded OpenCode dispatch budget so ordinary default-branch traffic cannot leave them at `OpenCode review absent`. It never uses the `.github` repository `github.token` for sibling mutations — it requires `PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, or the exchanged OpenCode app token, and fails with a visible `::error` reason when no cross-repository mutation credential is available instead of silently no-opping. Every swept repository prints its per-PR decision log, so an unmerged PR always has a concrete logged reason at most 15 minutes old.
- Queue hygiene posture: during the sweep, workflow runs still `queued` after `ORG_SWEEP_STALE_QUEUE_HOURS` (default 24h) are cancelled with their run id, workflow name, head branch, and age logged. A run queued that long belongs to a head that PR events will never revisit (closed PR, force-pushed branch, or a previous runner outage), and leaving it keeps the Actions queue holding non-current-head work.
- Inaccessible-repository posture: a sibling repository the sweep credential structurally cannot read — the OpenCode app is not installed there, or `PR_REVIEW_MERGE_TOKEN` does not cover it — returns HTTP 403 `Resource not accessible by integration` on every read. That is an access-grant fact the automation can never resolve, so the sweep classifies it as a skipped, non-fatal **unavailable** repository (a `::warning` naming the repository and the remediation) instead of a hard failure. Without this, a handful of un-enrolled repositories keeps the scheduled sweep heartbeat (the org sweep's `*/15 * * * *` cron) permanently red and masks a genuinely new repository that starts failing. Fail-closed is preserved on both sides: any non-403 scheduler failure still fails the sweep with its per-PR reason, and if more than `ORG_SWEEP_MAX_UNAVAILABLE` (default 5) repositories become unreachable in one pass — a credential-scope regression rather than a few un-enrolled repos — the job fails loudly. Remediation for a listed repository is to install the OpenCode app on it or grant `PR_REVIEW_MERGE_TOKEN` access.

## Second-reviewer (Noema) posture

The org's two-reviewer merge rule needs a second approving-review identity
independent of OpenCode. That identity is `cwl-noema-review[bot]`, supplied by
the organization-owned `cwl-noema-review` GitHub App. The central workflow
is an active organization required workflow. It runs the centrally versioned
`noema_review_gate.py` judgement path and
mints a short-lived installation token restricted to the target repository; the
App has read-only Actions/checks/contents/status/code-scanning/Dependabot access
and write access only to pull-request reviews.

The PydanticAI `ReviewAgent` product in `ContextualWisdomLab/noema`
(`reviewer/noema_reviewer`, noema#9) is the target standalone judgement plane,
while the central Python gate remains the deployed fail-closed reviewer. The
standalone package is not imported into the privileged workflow. External proof
exists on `ContextualWisdomLab/clearfolio#161`: `cwl-noema-review[bot]` submitted
an `APPROVED` review whose review commit, explicit Head SHA, current-head checks,
SARIF/dependency evidence, test evidence, and review marker all bind to
`4512fb9e9b56ab95df3acd85ebec2e6b849335a7`.

- Token posture: `noema-review.yml` prefers a `NOEMA_REVIEW_TOKEN` emergency
  fallback when present, otherwise mints the repository-scoped App token with
  `actions/create-github-app-token` pinned to an immutable SHA. The OIDC Worker
  exchange remains a compatibility fallback. If none of these identities is
  configured, the required check fails with the exact missing-credential reason;
  an unconfigured reviewer can never pass by skipping.
- Honesty posture: `noema_review_gate.py` refuses to review as a primary review
  actor (`opencode-agent`, `github-actions`), so a `NOEMA_REVIEW_TOKEN` that
  resolves to one of those identities cannot manufacture a fake second review —
  it must be a distinct write-access identity.
- Required admin config: install `cwl-noema-review` on the organization, set
  `NOEMA_GITHUB_APP_CLIENT_ID` plus `NOEMA_GITHUB_APP_PRIVATE_KEY`, and configure
  `NOEMA_LLM_MODEL`, `NOEMA_LLM_API_URL`, and either `NOEMA_LLM_API_KEY` or the
  shared `OPENAI_API_KEY`. Every missing setting is a visible failed-check reason.

## Scope

The active ruleset no longer maintains a repository-name allowlist. Live
ruleset inspection on 2026-07-02 18:15 KST reports
`repository_name.include=["~ALL"]`, so all current and future organization
repositories inherit the seven central required workflows on their default
branch unless a later ruleset exclusion is added. The table below is the public
non-fork inventory snapshot and rollout ledger, not the ruleset target list.

| Repository | Visibility | Default branch | Flow | Open PRs | Local central-workflow copies on default branch | Rollout status |
| --- | --- | --- | --- | ---: | --- | --- |
| `ContextualWisdomLab/.github` | public | `main` | GitHub Flow | 27 | central source; keep | single source of truth; central PRs through `#283` merged; PR `#286` current head queued after review-thread fixes |
| `ContextualWisdomLab/aFIPC` | public | `master` | GitHub Flow | 22 | none | central checks proven on PR `#78`; active queue still needs per-PR review |
| `ContextualWisdomLab/pg-erd-cloud` | public | `main` | GitHub Flow | 81 | none | repo-local autofix worker removed by PR `#393`; default branch now keeps only repository-owned application and security workflows |
| `ContextualWisdomLab/fast-mlsirm` | public | `main` | GitHub Flow | 25 | none | migrated; re-verify inherited checks on current open PRs |
| `ContextualWisdomLab/bandscope` | public | `develop` | Git Flow | 36 | none | no local central copies observed; verify inherited checks on active PRs |
| `ContextualWisdomLab/contextual-orchestrator` | public | `main` | GitHub Flow | 2 | none | default branch has no local central copies; current open PRs are runtime proof fixtures |
| `ContextualWisdomLab/naruon` | public | `develop` | Git Flow | 7 | none | default branch has no repo-local OpenCode, Strix, or scheduler copies; application/security workflows remain repository-owned |
| `ContextualWisdomLab/newsdom-api` | public | `develop` | Git Flow | 3 | none | local workflows already gone; re-verify inherited checks on current open PRs |
| `ContextualWisdomLab/appguardrail` | public | `develop` | Git Flow | 9 | none | migrated; re-verify inherited checks before final closure |
| `ContextualWisdomLab/scopeweave` | public | `develop` | Git Flow | 2 | none | local workflows already gone; re-verify inherited checks on current open PRs |
| `ContextualWisdomLab/ContextualWisdomLab.github.io` | public | `main` | GitHub Flow | 19 | none | migrated; re-verify inherited checks on current open PRs |
| `ContextualWisdomLab/codec-carver` | public | `main` | GitHub Flow | 42 | none | local workflows already gone; quality uplift still needs 100% test/docstring evidence before closure |
| `ContextualWisdomLab/clearfolio` | public | `main` | GitHub Flow | 57 | none | migrated; re-verify inherited checks before final closure |
| `ContextualWisdomLab/semantic-data-portal` | public | `main` | GitHub Flow | 3 | none | PR `#3` merged; default branch has no local central copies |
| `ContextualWisdomLab/hyosung-itx-slogan-brief` | public | `main` | GitHub Flow | 1 | none | migrated; re-verify inherited checks on current open PR |
| `ContextualWisdomLab/kaefa` | public | `develop` | Git Flow | 6 | none | newly discovered public non-fork target; ruleset inherited but current PR #60 lacked central check runs in status rollup |
| `ContextualWisdomLab/waf-ids-ai-soc` | public | `main` | GitHub Flow | 1 | none | newly discovered public non-fork target; PR #6 merged after central workflow proof; PR #8 is now the open current-head runtime proof fixture |

## Current policy

1. Security evidence, review evidence, and mechanical merge/update automation are centralized through the organization `workflows` ruleset rule.
2. The central required workflows come from `.github`; repositories should not receive copied Strix, OpenCode, Noema, or scheduler workflow files only to satisfy this rollout.
3. GitHub Flow repositories are those whose default branch is `main` or `master`.
4. Git Flow repositories are those whose default branch is `develop`.
5. OpenCode remains responsible for review judgment and structured decisions.
6. GitHub Actions remains responsible for mechanical branch updates and merges.
7. A merge is acceptable only when the current head has required checks passing, distinct current-head OpenCode and Noema approvals, no unresolved review threads, and a clean or mergeable merge state.
8. Previous-head approvals or checks are not merge evidence.
9. Same-repository approved PRs should merge immediately when GitHub reports `CLEAN`; fork or external-head PRs are excluded from scheduler merge and auto-merge.

## Evidence from this rollout

- On 2026-08-28 21:43 KST, ruleset `21732164` was created with active enforcement for every non-default branch. Reproduction on an existing LineageWeave PR head and a new branch returned GH013 before either ref could emit the required workflow event. The ruleset was returned to `evaluate` mode at 21:49 KST; the audit now fails if this impossible all-ref contract is reactivated.

- On 2026-06-30 08:33 KST, organization ruleset `18156473` was changed from an explicit repository-name list to `repository_name.include=["~ALL"]` while keeping `ref_name.include=["~DEFAULT_BRANCH"]` and the same three central required workflow paths from `.github@refs/heads/main`.
- On 2026-07-01 02:52 KST, ruleset `18156473` still reported `enforcement=active`, `repository_name.include=["~ALL"]`, `ref_name.include=["~DEFAULT_BRANCH"]`, and the three required workflow paths from `ContextualWisdomLab/.github@refs/heads/main`.
- On 2026-07-01 06:30 KST, organization ruleset `18156473` still reported `enforcement=active`, `repository_name.include=["~ALL"]`, `ref_name.include=["~DEFAULT_BRANCH"]`, and the three required workflow paths from `ContextualWisdomLab/.github@refs/heads/main`.
- On 2026-07-02 07:25 KST, organization ruleset `18156473` still reported `enforcement=active`, `repository_name.include=["~ALL"]`, `ref_name.include=["~DEFAULT_BRANCH"]`, and the same three required workflow paths from `ContextualWisdomLab/.github@refs/heads/main`.
- On 2026-07-11 11:30 KST, organization ruleset `18156473` was normalized to keep the five central required workflows, stale-review dismissal, last-pusher protection, and review-thread resolution while setting `required_approving_review_count=0` and `require_code_owner_review=false`. The merge gate remains current-head OpenCode approval plus required checks and scheduler evidence; the change removes self-authored/code-owner deadlocks that left approved PRs unable to merge.
- On 2026-07-13 21:10 KST, live inspection found that `sast-semgrep.yml` described itself as the central replacement for removed repository-local Semgrep jobs but was absent from ruleset `18156473`. The active ruleset was updated to require that workflow from `.github@refs/heads/main`, while preserving one approval, stale-review dismissal, last-push approval, and review-thread resolution. `scripts/ci/audit_central_required_workflows.py` and the scheduled ruleset audit now report each missing workflow, wrong source ref, or weakened review protection explicitly.
- On 2026-07-13 22:21 KST, the first main-branch ruleset audit proved that a repository `GITHUB_TOKEN` cannot read the organization-administration endpoint (`HTTP 403 Resource not accessible by integration`). The audit uses the least-privilege inherited-ruleset endpoint, logs `RULESET_SCOPE` for each enumerated repository, and validates the complete workflow and pull-request rule payload through `naruon`. The original public-only scope and its historical `.github`/`argos`/`noema` exclusions were superseded by the 2026-07-23 audit below.
- On 2026-07-13 22:37 KST, xtrmLLMBatchPython current-head evidence proved that Semgrep 1.169.0 reports zero blocking findings while retaining 23 source-suppressed results in raw SARIF. The central gate now logs the suppressed count, removes only SARIF results carrying explicit in-source suppressions before upload, and fails from the remaining SARIF finding count even when Semgrep's SARIF-mode exit code is zero.
- On 2026-07-16 14:18 KST, `ContextualWisdomLab/clearfolio#161` proved the independent reviewer on exact current head `4512fb9e9b56ab95df3acd85ebec2e6b849335a7`: `cwl-noema-review[bot]` submitted an App-authored `APPROVED` review whose body records the same Head SHA and cites the clean SARIF, dependency, test, and diff evidence.
- On 2026-07-23 06:35 KST, ruleset `18156473` was updated to require `.github/workflows/noema-review.yml`, making seven central required workflows while preserving exactly two approvals, stale-review dismissal, last-push approval, review-thread resolution, and merge/squash-only policy. The all-repository scope excludes only `.github`, `noema`, and private `IRT-bibliography-set`; `argos` now inherits the ruleset. The scheduled audit now enumerates every organization repository visible to its credential (`type=all`), rather than only public repositories, so the private exclusion and all other visible private-repository inheritance are verified. Existing open PRs may need a new PR event or branch update before GitHub creates the newly required Noema run.
- `.github` PR `#225` raised high reasoning effort for all reasoning-capable OpenCode review model definitions and merged at `50c6ef82f52af3eeb0e58c174902fc9855c36682`.
- `.github` PR `#226` stopped the merge scheduler from treating old deterministic fallback approval bodies as current-head approval evidence and merged at `57a1fa580731a0f76b31dcf29a597c5715dba2fd`.
- `.github` PR `#230` added changed-file candidates to merge-conflict guidance so `DIRTY` or `CONFLICTING` PRs name the first files to inspect instead of giving only generic conflict instructions. It merged at `0cab5c8d46e88c1a3f68ef3f71b5d44d971cd2ef`.
- `.github` PR `#232` removed the workflow-only deterministic approval fallback introduced by PR `#231`; model-pool exhaustion now stays on the fail-closed `REQUEST_CHANGES` path, and reasoning-capable OpenCode model candidates must have `reasoningEffort: high` before execution. It merged at `f545a9917933f8f81a76ea0044cbce0aae1ac5bd`.
- `.github` PR `#233` blocks false trivial approval reasons such as `Typo fix in documentation string` when current-head changed files include workflow, script/source, or test surfaces. It merged at `4ff660c8396b78a1b82aef8c316b26527864d450`.
- `.github` PR `#234` made approval-summary repair parse bullet-form changed-file evidence from bounded review logs, so changed-file evidence is not lost when the evidence section is rendered as a Markdown list. It merged at `da3a4a5788e7019229d66247c360b258b1a5b1f7`.
- `.github` PR `#235` changed the post-approval OpenCode merge-scheduler follow-up to prefer the workflow `github.token` for same-repository mechanical merge/update mutations, keeping secret/app fallbacks for cross-repository manual dispatch. It merged at `482b05c6c11d9da9895246406aca1c3bd8f6a691`.
- `.github` PR `#239` centralized the OpenCode reasoning-effort guard into `scripts/ci/assert_opencode_reasoning_effort.py`, reused it for the review model pool and failed-check diagnosis path, and merged at `2aa1fa36255a558bafca05567125ef7e44571976` after required OpenCode, Strix, Noema, coverage, and scheduler checks passed.
- `.github` PR `#242` added REST fallbacks for transient scheduler GraphQL read failures in open-PR and single-PR lookup paths, then merged at `0d2c6d9e7ae1bad947e7ee3629e2a412ac2ce248`.
- `.github` PR `#244` added the central `PR Review Autofix` worker and changed the fix scheduler to dispatch the central `.github` autofix worker by default while preserving explicit target-repository overrides. It merged at `4d2dd64028231b1154642bfe23b822fc3403e217`.
- `.github` PR `#246` hardened the OpenCode model pool after `pg-erd-cloud` PR `#393` exposed model exhaustion: full review policy is kept on disk behind a compact launcher prompt, context-window overflow skips same-model retries, additional cataloged tool-calling models are included, reasoning-capable candidates keep `reasoningEffort: high`, and the model pool now has a five-hour total retry budget. It merged at `f5f00b782ae4f7806f0e3197bf9b49c9c5a2cb91`.
- `.github` PR `#247` was closed without merge because its reviewed-merge-update fallback would have approved a current head from previous-parent approval evidence after model exhaustion. That path conflicts with the current fail-closed policy: model timeout, model-pool exhaustion, or missing usable control output must lead to retry, alternate model execution, or a source-backed request for changes, not deterministic approval.
- `.github` PR `#249` guarded the central PR Review Fix Scheduler so `CHANGES_REQUESTED` review states dispatch the central autofix worker only when the latest OpenCode review is on the current head, the merge state is `CLEAN` or `HAS_HOOKS`, and the review body does not indicate process-only blockers such as merge conflict, model-pool exhaustion, unresolved human review threads, failed checks, `coverage-evidence`, or failed Strix evidence. It merged at `dbd33b3a0384de0129aa082a210383188d012415` after current-head `coverage-evidence`, `strix`, `opencode-review`, `noema-review`, and `scan-pr-queue` all completed successfully.
- `.github` PR `#255` removed the remaining deterministic low-risk approval fallback from the OpenCode approval gate and changed `coverage-evidence` blocker handling to publish a `REQUEST_CHANGES` review event, producing the PR review state `CHANGES_REQUESTED`, instead of leaving only a failed check/log. It merged at `e2beae72b87a8817cd57f9f51bab3947353baa61`; the first current-head OpenCode run reached an `APPROVE` gate result but hit the OpenCode GitHub App installation rate limit while publishing the review, then a rerun published approval and native auto-merge completed.
- `.github` PR `#283` refreshed the central OpenCode model configuration so every reasoning-capable review candidate sets `reasoning=true`, `options.reasoningEffort: high`, and `variants.high.reasoningEffort: high`; non-reasoning fallback candidates remain available without a false effort claim. It merged at `ef9950e6b55bf943c0295e1df3e34c94210d21cc`.
- After PR `#255` merged, `ContextualWisdomLab/bandscope` PRs `#493`, `#494`, `#495`, and `#500` were rechecked for branch freshness. Merge simulation against `develop` found real conflicts rather than update-branch candidates: `#493` conflicts in `apps/desktop/src/App.tsx` plus the design-system docs, while `#494`, `#495`, and `#500` conflict in `docs/design-system/README.md`, `docs/design-system/component-contract.md`, and `docs/design-system/figma-to-code-workflow.md`. Each PR received a corrected conflict-resolution comment with the exact file list and merge/rebase repair commands.
- `ContextualWisdomLab/aFIPC` PR `#78` is no longer a target-coverage gap. It merged after current-head central `coverage-evidence`, `opencode-review`, `strix`, and `scan-pr-queue` checks all passed on head `b1ddafced86302f461e95259699f1efde5ec87c9`; the OpenCode review approved the same head on 2026-06-30 06:02:55Z.
- `ContextualWisdomLab/pg-erd-cloud` PR `#393` removed the repo-local `pr-review-autofix.yml` worker after the central autofix worker merged.
  The first OpenCode run on head `9d8eed5be47670b1b46f413295d9a6044d7327b2` exhausted the older model pool and requested changes.
  After `.github` PR `#246` merged, central OpenCode run `28485070313` approved the same head and the PR merged at `1e0d6a3dda5ea9afcd74dcd8380689672e1c8ef1` on 2026-07-01 00:33:50Z.
  Live default-branch content lookup returned 404 for `.github/workflows/pr-review-autofix.yml` after merge.
- Live non-fork inventory on 2026-07-02 18:15 KST found 17 public non-fork repositories, inherited ruleset `18156473` on `kaefa` and `waf-ids-ai-soc`, and no default-branch copies of `opencode-review.yml`, `strix.yml`, or `pr-review-merge-scheduler.yml` outside `.github`.
- `ContextualWisdomLab/waf-ids-ai-soc` PR `#6` merged at `e1c0a85fd4a8e6dd67039be43eb7f659fec22abd` after central required workflow proof on head `43b62b5f347d1532c81b5ae38d8e41b4494fd486`; PR `#8` current head `48d8b56a0f995829fc95de4fed129d1c33aaadff` is now the open runtime proof fixture with central and local Rust checks queued at the 2026-07-02 18:15 KST refresh.
- `ContextualWisdomLab/kaefa` inherits ruleset `18156473`, but PR `#60` current head `13c9089855fcdd34391173560ccf6935bac1eebe` showed only repo-local R-CMD-check, dependency-review, and CodeQL signals in status rollup. Treat this as a runtime proof gap until a new PR event or manual dispatch proves central OpenCode, Strix, and scheduler checks on a kaefa current head.
- `.github` scheduler default merge mode is now `direct_or_auto`: approved same-repository `CLEAN` PRs request immediate guarded merge, approved non-clean same-repository PRs can queue native auto-merge, and fork or external-head PRs are left for maintainer merge.
- OpenCode approval runs the trusted central merge scheduler script directly with `pr_number` and `max_prs=1`, so the just-reviewed PR is inspected immediately even when organization required workflows are not repo-local `workflow_dispatch` targets.
- `.github` PR `#74` changed OpenCode review model order to DeepSeek R1 first and added a catalog fallback pool.
- `.github` PR `#75` removed the Strix finding against the scheduler command wrapper by using `subprocess.run(..., check=True)` and preserving the existing scrubbed failure contract.
- `.github` main Strix run `28218982899` passed after PR `#75` merged.
- `.github` PR `#77` merged the central OpenCode required-workflow path.
- `.github` PR `#77` same-head OpenCode proof run `28224085121` passed coverage evidence, CodeGraph initialization, bounded evidence preparation, model review, review comment publication, and approval-gate publication on head `59a8da0b2f56b862f6c5a0c69885f4045d6dc732`.
- `.github` PR `#77` central Strix required workflow run `28223698075` passed on the same head before merge.
- Organization ruleset `18156473` was renamed to `CWL Central required workflows` and required `.github/workflows/strix.yml` and `.github/workflows/opencode-review.yml` from `.github@main` SHA `6440d493816f8a4d66e32f2e5e8e6a9156d7f488`.
- `.github` PR `#79` merged the central scheduler `pull_request_target` path and PR-scoped `--pr-number` lookup.
- `.github` PR `#79` second current-head proof passed coverage evidence in 10s, Strix in 8m33s, and OpenCode review in 8m57s on head `17c62f3809c57ca4b1a9a63e14f325c9f2a1acdb`.
- Organization ruleset `18156473` now requires `.github/workflows/strix.yml`, `.github/workflows/opencode-review.yml`, and `.github/workflows/pr-review-merge-scheduler.yml` from `.github@main` SHA `807254a04efafd5f806e0f70cb067ecf050cfd11`.
- `.github` PR `#85` installed target repository `requirements.txt` before Python coverage evidence, so central coverage measurement can run repo tests that require project dependencies.
- `.github` PR `#88` hardened the OpenCode output normalizer so the Python normalizer is part of the trusted approval gate path.
- `.github` PR `#94` hardened the central OpenCode prompt and generated review DAG contract so Mermaid labels are quoted and render safely.
- `.github` PR `#95` blocks OpenCode approvals that claim no source, test, or executable changes when exact changed-file evidence lists workflow, script, source, or test files.
- On 2026-06-28 20:09 KST, ruleset `18156473` was re-pinned to `.github@main` SHA `531482764986bf7da98c1317d59e6e51e7c61d02` for all three required workflow paths.
- `ContextualWisdomLab/naruon` reports inherited active ruleset `18156473` with all three required workflow paths, proving target-repository inheritance after the scheduler ruleset update.
- `ContextualWisdomLab/ContextualWisdomLab.github.io` PR `#25` merged the thin central scheduler caller and repository-local bootstrap fixes. Its main Strix run `28217860369` passed.
- The organization ruleset API reports the central required workflows ruleset as `active` and inherited by each public non-fork target repository.
- `.github` PR `#100` added required-workflow job rerun support and cancels older same-PR OpenCode runs before retrying the current head. Local verification on head `3c62c37a4deabdb0c6ed4ddf0951c1987f09866b`: `pytest -q` passed 38 tests, `coverage report --fail-under=100` reported 100%, `interrogate --fail-under=100 .` reported 100%.
- `.github` PR `#100` merged at 2026-06-29 05:45 KST with merge commit `81408f3dbe0a3c43dc4b76133f72a5e314df8a10`. A follow-up admin check should verify organization ruleset `18156473` is no longer pinned to `refs/heads/codex/rerun-required-opencode-job`.
- The earlier 2026-06-29 KST `aFIPC` PR `#78` target-coverage gap is closed. A later current-head run on `b1ddafced86302f461e95259699f1efde5ec87c9` produced central `coverage-evidence`, `opencode-review`, `strix`, and `scan-pr-queue` success before merge.
- `.github` PR `#136` changed approved stale PR handling so `BEHIND` branches are updated before failed-check or `ACTION_REQUIRED` decisions disable auto-merge.
- `.github` PR `#137` made the central `PR Review Fix Scheduler` target-repository aware through `workflow_call`, `workflow_dispatch`, schedule, and `.github` repository variables. `.github` variables currently target `ContextualWisdomLab/pg-erd-cloud` on `main`. The follow-up central autofix worker makes `ContextualWisdomLab/.github` the default `autofix_repository`, so target repositories no longer need to copy a full `pr-review-autofix.yml` worker to participate.
- `.github` PR `#138` added compare-API branch freshness evidence so approved PRs with auto-merge enabled can still receive `update-branch` when GitHub reports `BLOCKED` but the base branch is ahead. Local verification passed `pytest -q`, scheduler self-test, `py_compile`, 100% coverage, 100% docstring coverage, `actionlint`, `bash -n`, and `git diff --check`.
- `.github` PR `#140` extended `update-branch` handling to PRs where auto-merge is already enabled even if the scheduler cannot find a current-head OpenCode approval node, so queued auto-merge PRs with failed checks can still be refreshed when compare evidence shows the base branch is ahead. Local verification passed `pytest -q`, `coverage report` at 100%, `interrogate` at 100%, `py_compile`, `bash -n`, and `git diff --check`.
- `.github` PR `#145` treats compare API `status: behind` as branch-staleness evidence even when `behind_by` is missing or zero, so an auto-merge-enabled PR with failed checks and a visible GitHub "Update branch" action requests `update_branch` before disabling auto-merge. It merged at 2026-06-29 23:14 KST with merge commit `1ec0f3dcc7250fdf4a5a3ec6c26feaa98cce4f48`.
- Live dry runs on 2026-06-30 00:40 KST found update-branch candidates in `.github` PR `#147` and `naruon` PR `#803`. The follow-up scheduler trigger change runs the central queue scan after base-branch pushes and `auto_merge_enabled` events, so those UI-visible stale-branch states are not left waiting only for the periodic schedule.
- `.github` PR `#151` added protected base-branch `push` triggers and the `auto_merge_enabled` PR event to the central scheduler, then merged at 2026-06-30 00:56 KST with merge commit `00018f7783522447a71acd08a946e3504e18ff74`. The merge created push-triggered scheduler run `28385177585`, proving the new trigger path is registered; the job remained queued because runner assignment was still pending.
- The earlier compare API `behind` handling is superseded by the current immediate-action order: `CLEAN` and current-head approved PRs merge before update-branch, failed or `ACTION_REQUIRED` checks are surfaced before any update attempt, and only approved `BEHIND` PRs without current-head check blockers request `update-branch` through the configured scheduler mutation credential.
- `.github` PR `#146` taught central OpenCode `coverage-evidence` to discover nested requirements-only Python test projects such as `backend/requirements.txt` plus `backend/tests`, install those requirements, and run tests from that project directory. It merged at 2026-06-29 23:24 KST with merge commit `0393bc1c48b80597d6d35c336aca43aee18e22b9`.
- `.github` PR `#149` tightened the central OpenCode model-failure path and merged at 2026-06-30 00:26 KST with merge commit `919b83faf29237803cfdd0cfd6febbe5ae1a8a3c`. The follow-up commit `6fdffe43b50a2246b3db2790a0ab532618a89c2b` fixed the fallback approval path so pending-check and human-thread evidence are written to real temporary files instead of empty paths. Local verification passed `pytest -q`, `coverage report --fail-under=100`, `interrogate --fail-under=100`, `actionlint -shellcheck=`, targeted OpenCode quick-gate assertions, `bash -n`, and `git diff --check`; the full quick-gate script exceeded the local 300s timeout in this environment.
- Organization ruleset `18156473` previously targeted all live non-fork repositories, including private `aFIPC`, `linux-cluster-ops`, and `xtrmLLMBatchPython`; this has been superseded by the all-repository `~ALL` condition above.
- `ContextualWisdomLab/semantic-data-portal` PR `#3` removed repo-local OpenCode, Strix, and scheduler workflows; the default branch now has no `.github/workflows` directory.
- `ContextualWisdomLab/pg-erd-cloud` PR `#361` removed the repo-local `pr-review-fix-scheduler.yml` wrapper after central `.github` gained target repository support. It merged at 2026-06-29 22:40 KST with merge commit `21cbc14b21d59ac28ac789de58502816cc8df6ad`; live default-branch content lookup returned 404 for that wrapper path after merge.
- `ContextualWisdomLab/naruon` classic branch protection no longer requires direct `strix` or `opencode-review` status checks on `develop`; after deletion, `branches/develop/protection/required_status_checks` returns `404 Required status checks not enabled`, while org ruleset `18156473` remains `active` and still targets `naruon`.
- `ContextualWisdomLab/naruon` PR `#852` rewrites `backend/tests/test_release_governance.py` and `docs/development/merge-gate-policy.md` to make the central scheduler the contract, then deletes the repo-local `pr-review-merge-scheduler.yml`. The first current-head central `coverage-evidence` failed because nested `backend/requirements.txt` was not installed; `.github` PR `#146` fixed that central path. PR `#852` was pushed to head `2c8257ce0d02838b80650997d65e85569f4ab27f` to generate fresh required workflows from the updated central main. The stale OpenCode `CHANGES_REQUESTED` review `4592643416` on previous head `0f103836f15d9055c4ed85152f925a6e9514adb2` was dismissed on 2026-06-30 00:25 KST; the PR now requires fresh current-head OpenCode/coverage evidence and still has queued `coverage-evidence`.

## Good patterns to keep

- `naruon`: separates PR Governance, OpenCode review, Strix evidence, and application CI into explicit checks.
- `.github`: centralizes reusable workflow logic and review/merge scheduler code.
- `pg-erd-cloud`: its previous repo-local autofix worker was folded into the central `PR Review Autofix` worker and removed from the repository by PR `#393`; keep only repository-specific application and security checks locally.
- `ContextualWisdomLab.github.io`: thin caller pattern is acceptable for repository-local workflows only when GitHub does not offer an organization-level control. It should not be the default rollout mechanism.

## Risks and follow-up

- Existing open PRs may need a new push or base update before the latest required workflow SHA appears on their current head.
- The central OpenCode workflow now retries DeepSeek R1, DeepSeek V3, GPT-5, and a catalog fallback pool. Keep model/tooling failures out of PR comments unless there is a source-backed failed-check diagnosis.
- The central OpenCode config includes a read-only `code-reviewer` subagent for focused review passes. The subagent may read, grep, glob, and run safe local verification commands, but it must not edit files, stage changes, commit, push, install dependencies, mutate branches, or touch production state.
- OpenCode execution evidence must be sandboxed in the CI workspace or an isolated temporary directory, with a credential-scrubbed environment by default and no persistent mutation outside test caches or scratch files. Prefer `python3 scripts/ci/sandboxed_verify.py --repo-root <reviewed worktree> -- <verification command>` when the central helper is available, and cite its `SANDBOXED_VERIFY_RESULT` line. When repo-native verification legitimately needs network access or GitHub Secrets, pass only the needed names with `--allow-env`, record `--network required`, and explain it with `--evidence-note` without printing secret values. The helper does not replace existing bash, task, webfetch, websearch, lsp, CodeGraph, DeepWiki, Context7, or web_search review policy. If a verification cannot be sandboxed without changing the result, the review must say so instead of presenting an unsafe run as evidence.
- Web application reviews should run backend, frontend, and repository-native E2E checks together through `python3 scripts/ci/sandboxed_web_e2e.py --repo-root <reviewed worktree> --backend-cmd <backend command> --frontend-cmd <frontend command> --e2e-cmd <e2e command>` when those contracts exist, then cite `SANDBOXED_WEB_E2E_RESULT`. If backend/frontend/E2E/readiness contracts are missing, the review must name the gap instead of treating unit or lint evidence as full E2E proof.
- Bounded OpenCode evidence includes `Review execution contracts`, which inventories runtime matrices, package manifests, test, coverage, docstring, E2E, lint, security, Docker, and unpackaged-source gaps before the model chooses verification commands.
- Generated OpenCode review DAGs must use quoted Mermaid labels such as `A["text"]`; unquoted labels with spaces, punctuation, parentheses, or file counts can fail to render.
- OpenCode approval summaries must not contradict exact changed-file evidence by saying no source, test, or executable files changed when workflow, script, source, or test files are present.
- OpenCode approval reasons must not trivialize material workflow, script/source, or test changes as docs-only, typo-only, or string-only changes. The normalizer now rejects those approvals before publication.
- Same-repository post-approval merge/update follow-up should use the workflow `github.token` first so the mechanical actor is `github-actions[bot]`; cross-repository manual dispatch may still fall back to configured secrets or the OpenCode app token when the workflow token cannot mutate the target repository.
- Do not copy central Strix, OpenCode, merge scheduler, fix scheduler, or autofix worker workflows into repositories. Repository-local application CI and security CI may remain when they are not substitutes for the central workflows.
- The central autofix worker is for source-actionable current-head review findings. It must not treat model-pool exhaustion, missing approval evidence, unresolved human threads, failed checks, `coverage-evidence`, Strix failures, `DIRTY`, or `CONFLICTING` merge states as code-autofix requests; those states need retry, failed-check explanation, branch update, or conflict guidance instead.
- `pg-erd-cloud` no longer has a repository-local `pr-review-autofix.yml` worker on its default branch. Live default-branch workflows after PR `#393` are `ci.yml`, `codeql-backfill.yml`, `codeql.yml`, `dependency-review.yml`, and `scorecard.yml`.
- Some repositories use classic branch protection while others use rulesets. Normalize branch protection into rulesets without removing repository-specific required application checks.
- Existing PRs may not show newly inherited required workflows until a new PR event or branch update occurs, even though the org ruleset now uses the all-repository condition.
