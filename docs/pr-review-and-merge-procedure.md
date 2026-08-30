# PR review and merge procedure

Bot and agent operating contract for ContextualWisdomLab PR review, exact-head
CI, successor heads, writer boundaries, and mechanical merge. The
buyer/operator overview lives in [README.md](../README.md). The live audit and
per-repository DX/UX transfer decisions live in
[PR_GOVERNANCE_AUDIT.md](../PR_GOVERNANCE_AUDIT.md). Rollout and ruleset
posture live in [org-required-workflow-rollout.md](org-required-workflow-rollout.md).

This file keeps the operational truth that used to sit in the root README.
Do not treat a sibling product composing into naruon as a defect of this
control plane. Naruon is the composition hub; this repository still runs
alone as the org profile and workflow source.

## Actors and writer boundaries

OpenCode judges PRs; GitHub Actions performs mechanical updates and merges.
The configured `code-reviewer` subagent is reviewer-only: it may read, grep,
glob, and run safe local verification commands, but it must not edit files,
stage changes, commit, push, install dependencies, mutate branches, or touch
production state. Blocking findings must be source-backed, severity-labeled,
impactful, remediable, and include suggested verification.

The OpenCode review job does not widen its own `pull_request_target` job token
to repository-write permission. The scheduler's `GH_TOKEN` merge/read fallback
order is `PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, the exchanged
OpenCode app token, then the receiving workflow's `github.token`. For
repository-dispatch calls that target another repository, the
`SCHEDULER_ACTIONS_TOKEN` and `SCHEDULER_READ_TOKEN` values use the same first
three explicit credentials and do not fall back to a central-repository token;
for same-repository calls they may use `github.token`. A central
`github.token` cannot mutate or read a different target repository, so the
scheduler leaves that cross-repository operation blocked when no explicit
credential is available; the separate required workflow and schedule remain
authoritative.

Branch updates and merges run through the central scheduler mutation
credential, in this order:

1. `PR_REVIEW_MERGE_TOKEN`
2. `OPENCODE_APPROVE_TOKEN`
3. the exchanged OpenCode GitHub App token
4. the target workflow token

The scheduler reports the credential class in its decision output.

## Exact-head CI and successor heads

The scheduler updates a same-repository PR branch only when the latest
OpenCode review is approved, no current-head failed check is present, and
GitHub reports the PR as behind. After that update, the new head is a
successor head: it must pass OpenCode, Strix, required checks, and
review-thread gates again before auto-merge or `--match-head-commit` merge
can proceed.

Post-approval reuse and follow-up accept only an exact-head review authored
by the OpenCode GitHub App. A GitHub Actions-authored review is not OpenCode
approval evidence. The separate scheduler also listens for that App review,
waits for the publishing OpenCode check to finish, and then retries direct
merge outside the review job when repository auto-merge is unavailable.

Every merge keeps `--match-head-commit`. It prefers squash and retries with a
merge commit only when the target repository explicitly reports that squash
is disabled.

Superseded queued or running workflow cleanup remains mandatory, but a GitHub
cancel or force-cancel API failure cannot make an old head authoritative or
block a policy-clean current head. The scheduler logs the exact run id and
bounded API error as an Actions warning, then continues the current-head
decision.

Metadata-free `workflow_run` scheduler events use a workflow-run-specific
default-branch fallback concurrency group, separate from push runs. They
therefore cancel older runs in that group, and the organization sweep keeps
only the newest same-HEAD central scheduler scan. This cleanup is limited to
the exact scheduler workflow, the default branch, and an empty
`pull_requests` list; push, PR-associated, and unrelated workflow runs remain
eligible for their own queue decisions.

Old approvals and old checks are not merge evidence after the head SHA
changes. OpenCode review evidence must be internally same-head as well as
GitHub-attached same-head. If the review body includes `Gate evidence` with
`Head SHA: <sha>`, that SHA must match the PR current `headRefOid`.

A current-head OpenCode `CHANGES_REQUESTED` review normally blocks the PR. The
only retry exception is the exact automation review stating that approval was
withheld because GitHub Checks failed and listing those failed checks. After
the live rollup is empty, the scheduler may dispatch a fresh same-head
OpenCode review when review dispatch is enabled and no native auto-merge
request is active. It never treats the recovered checks as approval, dismisses
the existing review, or merges until a new exact-head OpenCode approval exists.

## Do-not-merge and DIRTY / CONFLICTING repair

The `update_branch` path is deliberately not used for `DIRTY` or
`CONFLICTING` PRs. GitHub cannot synthesize a safe conflict resolution for
the author, so the merge scheduler must give the author a repair path instead
of pretending the merger can fix it.

A current-head approved PR may still keep or queue native GitHub auto-merge
while the conflict is repaired. Queued auto-merge is a wait state, not
evidence that the conflict is solved. When GitHub reports `DIRTY` or
`CONFLICTING`, the scheduler blocks the PR with repair guidance: merge or
rebase the latest base branch into the PR branch, resolve conflict markers in
that PR branch, rerun focused checks, and push the same branch. OpenCode
comments must include a compact command block covering `gh pr checkout`,
`git fetch`, merge or rebase, `git status --short`, resolved-file staging,
normal push, and `--force-with-lease` only for rebased branches.

Separately, the edit-capable autofix flow
(`scripts/ci/pr_review_fix_scheduler.py` →
`.github/workflows/pr-review-autofix.yml`) may, for an approved
same-repository-head PR, merge the base into the head and resolve the
conflict markers with OpenCode, then push the resolved head. That head is
fully re-reviewed and re-checked before it can merge, so a wrong resolution
cannot merge unreviewed.

## Head mutations need a workflow-starting credential

GitHub never starts a new workflow run for an event created with the workflow
`GITHUB_TOKEN` (GitHub, 2025). A PR head moved with that credential therefore
collects no current-head required checks, so a protected PR that requires
current-head checks stays `BLOCKED` forever and no later scheduler run can
repair it, because the branch is no longer behind.

The scheduler now refuses both head mutations, `update-branch` and the
last-push approval head restamp, whenever `SCHEDULER_MUTATION_TOKEN_SOURCE`
resolves to `github-token`. It records a `WAIT` decision with
`head_mutation_credential_upgrade` guidance instead: configure
`PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, or keep the OpenCode app
token exchange available for the scheduler job, or let the PR author push the
branch so required checks rerun on the new head.

Reference: GitHub. (2025). *Automatic token authentication*.
<https://docs.github.com/actions/security-for-github-actions/security-guides/automatic-token-authentication>

## Central required workflows, not local copies

Strix, OpenCode, Noema, and the scheduler are sourced from the central
`ContextualWisdomLab/.github` workflows rather than copied into each
repository. Required-workflow runs execute in the target repository context,
so mechanical branch updates, stale-thread resolution, and merges use the
configured central mutation credential while the trusted implementation still
comes from the central repository.

The scheduler dispatches same-head Strix evidence first, then dispatches
OpenCode for the same PR head when review evidence is missing or stale. This
avoids running PR-head review, CodeGraph, coverage, or PoC code as an
unbounded local workflow copy.

Scheduled review-feedback autofix is also centralized. The
`PR Review Fix Scheduler` dispatches the central `PR Review Autofix` worker
in `ContextualWisdomLab/.github` and passes the target repository, PR number,
base SHA, head ref, and head SHA as explicit inputs. The worker mutates only
same-repository PR heads, rechecks the live head before checkout and before
push, and commits as `github-actions[bot]` only when a conservative OpenCode
autofix produces a validated diff. A repository-local autofix worker remains
an explicit compatibility override through `--autofix-repository`; it is no
longer the default contract.

Strix keeps `cancel-in-progress: false` so old evidence is not cancelled by a
force-push, but PR-scoped concurrency includes the head SHA so an obsolete
scan does not serialize newer current-head evidence.

## Approve-gate evidence

OpenCode approval is evidence-gated. Before approval, the review summary must
name changed files, CodeGraph or structural MCP evidence, a Change Flow DAG,
passing supported test-suite evidence, configured docstring-gate evidence or
advisory docstring status, and a concrete PoC/execution result. It must also
split `Developer experience:` from `User experience:` so
maintainability/review/CI friction is not confused with product,
documentation, review-comment, or status-check reader outcomes.

The PoC can be a temporary scratch repro, focused test, lint, security check,
performance probe, or UI verification command, but it must be actually run
and cited. Every adversarial probe must also state an observed result such as
an exit code, passed or failed test/assertion, rejected input, log value, or
source trace outcome. Generic `source inspection` or `test coverage verifies`
prose without that observation is not reusable approval evidence.

Execution evidence must be sandboxed in the CI workspace or an isolated
temporary directory, with a credential-scrubbed environment by default and no
persistent mutation outside test caches or scratch files. When repo-native
verification legitimately needs network access or GitHub Secrets, pass only
the specific environment variable names required and record why they were
needed. The central helper is
`python3 scripts/ci/sandboxed_verify.py --repo-root <reviewed worktree> --
<verification command>`; reviews should cite its `SANDBOXED_VERIFY_RESULT`
line when the helper is used. Use `--network required`, `--allow-env NAME`,
and `--evidence-note "why"` only for repository-required verification. This
helper does not replace the existing bash, task, webfetch, websearch, lsp,
CodeGraph, DeepWiki, Context7, or web_search review policy.
Scratch PoC files are not committed.

For web applications with both backend and frontend surfaces, the preferred
execution proof is the central E2E helper:
`python3 scripts/ci/sandboxed_web_e2e.py --repo-root <reviewed worktree>
--backend-cmd <backend command> --frontend-cmd <frontend command> --e2e-cmd
<e2e command>`. Reviews should include readiness URLs when the repository
defines them and cite `SANDBOXED_WEB_E2E_RESULT`. If a repo lacks an
executable backend, frontend, E2E, or readiness contract, the review must
name the missing contract instead of presenting a partial run as full E2E
evidence.

OpenCode bounded evidence also includes a `Review execution contracts`
section that discovers runtime matrices, package manifests, test, coverage,
docstring, E2E, lint, security, Docker, and unpackaged-source gaps before the
agent chooses commands.

Failed GitHub Checks are not reviewed as URL lists. OpenCode must explain the
failed check name, failing step, source-backed file and line when available,
root cause, fix direction, and focused rerun command. Cancelled or superseded
checks must be described as queue or evidence blockers rather than invented
source-code findings.

CodeRabbit or other current-head evidence may inform the review, but it does
not replace exact-head OpenCode approval, same-head Strix evidence, or the
scheduler `--match-head-commit` guard.

## Operational cases

- `naruon`: approved PRs can become `BEHIND`; the scheduler treats that as an
  update request, not as a merge signal. GitHub Actions updates the branch
  with `expected_head_sha`, then the new head is reviewed again. Naruon is
  the composition hub that receives other CWL products; that composition is
  not a control-plane bug and does not change this repository's standalone
  run.
- `pg-erd-cloud`: successful bot merges used current-head evidence and
  `--match-head-commit`; the centralized path keeps that head-SHA guard.
- `.github`: PRs that edit trusted review workflows can fail because
  `pull_request_target` runs the base branch's trusted scripts. A same-head
  manual `workflow_dispatch` Strix run may supply evidence for review, but it
  does not replace required PR checks until the trusted base branch catches
  up.
- `ContextualWisdomLab/naruon#745`: new OpenCode review-flow work improves
  Mermaid output by replacing generic risk sketches with changed-file flow
  DAGs. The central workflow carries that review contract while keeping the
  self-test drift fix.
- Cross-repo DX/UX: helpful sibling-repo patterns should be adopted when they
  reduce maintainer, reviewer, CI-operator, contributor, user, or reader
  friction. Noisy automation, repeated waiting, false failures, misleading
  statuses, and URL-only diagnostics are treated as review-experience
  defects.
