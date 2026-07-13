# Contextual Wisdom Lab

Organization profile repository for **맥락지혜 연구실 / Contextual Wisdom Lab**.

The public GitHub organization profile lives in [profile/README.md](profile/README.md).

Homepage: https://contextualwisdomlab.github.io/

PR governance live audit: [PR_GOVERNANCE_AUDIT.md](PR_GOVERNANCE_AUDIT.md).
The audit includes repository-by-repository DX/UX transfer decisions: what the
central workflow borrows because it reduces friction, and what it rejects
because it adds noise or misleading review experience.

## PR review and merge policy

OpenCode judges PRs; GitHub Actions performs mechanical updates and merges.
The scheduler updates a same-repository PR branch only when the latest OpenCode
review is approved, no current-head failed check is present, and GitHub reports
the PR as behind. After that update, the new head must pass OpenCode, Strix,
required checks, and review-thread gates again before auto-merge or
`--match-head-commit` merge can proceed.
Branch updates and merges run through the central scheduler mutation credential:
`PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, the exchanged OpenCode GitHub
App token, or finally the target workflow token. The scheduler reports the
credential class in its decision output. The OpenCode review job does not widen
its own `pull_request_target` job token to repository-write permission; its
immediate post-approval scheduler follow-up uses only an explicit merge token or
the OpenCode app token, otherwise it leaves the separate scheduler required
workflow and schedule authoritative.
Post-approval reuse and follow-up accept only an exact-head review authored by
the OpenCode GitHub App; a GitHub Actions-authored review is not OpenCode
approval evidence. The separate scheduler also listens for that App review,
waits for the publishing OpenCode check to finish, and then retries direct merge
outside the review job when repository auto-merge is unavailable. Every merge
keeps `--match-head-commit`; it prefers squash and retries with a merge commit
only when the target repository explicitly reports that squash is disabled.
Superseded queued or running workflow cleanup remains mandatory, but a GitHub
cancel or force-cancel API failure cannot make an old head authoritative or
block a policy-clean current head. The scheduler logs the exact run id and
bounded API error as an Actions warning, then continues the current-head
decision.
That `update_branch` path is deliberately not used for `DIRTY` or
`CONFLICTING` PRs: GitHub cannot synthesize a safe conflict resolution for the
author, so the merge scheduler must give the author a repair path instead of pretending
the merger can fix it. A current-head approved PR may still keep or queue native
GitHub auto-merge while the conflict is repaired; queued auto-merge is a wait
state, not evidence that the conflict is solved. Separately, the edit-capable
autofix flow (`scripts/ci/pr_review_fix_scheduler.py` →
`.github/workflows/pr-review-autofix.yml`) may, for an approved
same-repository-head PR, merge the base into the head and resolve the conflict
markers with OpenCode, then push the resolved head; that head is fully
re-reviewed and re-checked before it can merge, so a wrong resolution cannot
merge unreviewed.
When GitHub reports `DIRTY` or `CONFLICTING`, the scheduler does not pretend to
fix the branch. It blocks the PR with repair guidance: merge or rebase the
latest base branch into the PR branch, resolve conflict markers in that PR
branch, rerun focused checks, and push the same branch. OpenCode comments must
include a compact command block covering `gh pr checkout`, `git fetch`, merge or
rebase, `git status --short`, resolved-file staging, normal push, and
`--force-with-lease` only for rebased branches.

Strix, OpenCode, and the scheduler are sourced from the central
`ContextualWisdomLab/.github` workflows rather than copied into each repository.
Required-workflow runs execute in the target repository context, so mechanical
branch updates, stale-thread resolution, and merges use the configured central
mutation credential while the trusted implementation still comes from the
central repository. The scheduler dispatches same-head Strix evidence first,
then dispatches OpenCode for the same PR head when review evidence is missing or
stale.
This avoids running PR-head review, CodeGraph, coverage, or PoC code as an
unbounded local workflow copy.
Scheduled review-feedback autofix is also centralized. The
`PR Review Fix Scheduler` dispatches the central `PR Review Autofix` worker in
`ContextualWisdomLab/.github` and passes the target repository, PR number, base
SHA, head ref, and head SHA as explicit inputs. The worker mutates only
same-repository PR heads, rechecks the live head before checkout and before
push, and commits as `github-actions[bot]` only when a conservative OpenCode
autofix produces a validated diff. A repository-local autofix worker remains an
explicit compatibility override through `--autofix-repository`; it is no longer
the default contract.
Strix keeps `cancel-in-progress: false` so old evidence is not cancelled by a
force-push, but PR-scoped concurrency includes the head SHA so an obsolete scan
does not serialize newer current-head evidence.

OpenCode approval is evidence-gated. Before approval, the review summary must
name changed files, CodeGraph or structural MCP evidence, a Change Flow DAG,
passing supported test-suite evidence, configured docstring-gate evidence or advisory docstring status, and a concrete
PoC/execution result. It must also split `Developer experience:` from
`User experience:` so maintainability/review/CI friction is not confused with
product, documentation, review-comment, or status-check reader outcomes. The PoC
can be a temporary scratch repro, focused test, lint, security check,
performance probe, or UI verification command, but it must be actually run and
cited. Every adversarial probe must also state an observed result such as an
exit code, passed or failed test/assertion, rejected input, log value, or source
trace outcome. Generic `source inspection` or `test coverage verifies` prose
without that observation is not reusable approval evidence. Execution evidence
must be sandboxed in the CI workspace or an isolated
temporary directory, with a credential-scrubbed environment by default and no
persistent mutation outside test caches or scratch files. When repo-native
verification legitimately needs network access or GitHub Secrets, pass only the
specific environment variable names required and record why they were needed.
The central helper is
`python3 scripts/ci/sandboxed_verify.py --repo-root <reviewed worktree> --
<verification command>`; reviews should cite its `SANDBOXED_VERIFY_RESULT` line
when the helper is used. Use `--network required`, `--allow-env NAME`, and
`--evidence-note "why"` only for repository-required verification. This helper
does not replace the existing bash, task, webfetch, websearch, lsp, CodeGraph,
DeepWiki, Context7, or web_search review policy. Scratch PoC files are not
committed.
For web applications with both backend and frontend surfaces, the preferred
execution proof is the central E2E helper:
`python3 scripts/ci/sandboxed_web_e2e.py --repo-root <reviewed worktree>
--backend-cmd <backend command> --frontend-cmd <frontend command> --e2e-cmd
<e2e command>`. Reviews should include readiness URLs when the repository
defines them and cite `SANDBOXED_WEB_E2E_RESULT`. If a repo lacks an executable
backend, frontend, E2E, or readiness contract, the review must name the missing
contract instead of presenting a partial run as full E2E evidence.
OpenCode bounded evidence also includes a `Review execution contracts` section
that discovers runtime matrices, package manifests, test, coverage, docstring,
E2E, lint, security, Docker, and unpackaged-source gaps before the agent chooses
commands.
The configured `code-reviewer` subagent is reviewer-only: it may read, grep,
glob, and run safe local verification commands, but it must not edit files,
stage changes, commit, push, install dependencies, mutate branches, or touch
production state. Blocking findings must be source-backed, severity-labeled,
impactful, remediable, and include suggested verification.

Failed GitHub Checks are not reviewed as URL lists. OpenCode must explain the
failed check name, failing step, source-backed file and line when available,
root cause, fix direction, and focused rerun command. Cancelled or superseded
checks must be described as queue or evidence blockers rather than invented
source-code findings.

Operational cases folded into the central policy:

- `naruon`: approved PRs can become `BEHIND`; the scheduler treats that as an
  update request, not as a merge signal. GitHub Actions updates the branch with
  `expected_head_sha`, then the new head is reviewed again.
- `pg-erd-cloud`: successful bot merges used current-head evidence and
  `--match-head-commit`; the centralized path keeps that head-SHA guard.
- `.github`: PRs that edit trusted review workflows can fail because
  `pull_request_target` runs the base branch's trusted scripts. A same-head
  manual `workflow_dispatch` Strix run may supply evidence for review, but it
  does not replace required PR checks until the trusted base branch catches up.
- `naruon#745`: new OpenCode review-flow work improves Mermaid output by
  replacing generic risk sketches with changed-file flow DAGs. The central
  workflow carries that review contract while keeping the self-test drift fix.
- Cross-repo DX/UX: helpful sibling-repo patterns should be adopted when they
  reduce maintainer, reviewer, CI-operator, contributor, user, or reader
  friction. Noisy automation, repeated waiting, false failures, misleading
  statuses, and URL-only diagnostics are treated as review-experience defects.
