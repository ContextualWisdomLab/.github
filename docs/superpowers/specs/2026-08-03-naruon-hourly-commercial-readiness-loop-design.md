# Naruon Hourly Commercial Readiness Loop Design

## Approval source

The product owner explicitly requested autonomous, hourly execution without routine intermediate reports. That mandate authorizes this bounded design and its implementation while preserving repository rules, required reviews, and safety gates.

## Purpose

Continuously move `ContextualWisdomLab/naruon` toward commercial readiness by running one deterministic loop every hour:

1. inspect every open pull request;
2. dispatch review-feedback fixes for actionable current-head findings;
3. refresh required OpenCode and Strix evidence;
4. revalidate required checks;
5. merge only when repository rules permit;
6. when the open PR count is zero, implement exactly one buyer-visible product gap on a new branch and open a normal pull request;
7. repeat.

The loop serves Naruon's founding jobs: finding email context and tracking changing email-borne schedules. It must not turn Naruon into groupware, an approval engine, an HRIS, or an ERP.

## Goals

- Keep the safely mergeable open-PR count at zero.
- Repair current-head review findings rather than bypassing them.
- Create no direct commits to `develop`.
- Produce at most one product-development PR when the queue is empty.
- Prefer buyer-visible improvements to email retrieval, context synthesis, schedule truth, conflict detection, evidence, accessibility, privacy, reliability, interoperability, and deployment readiness.
- Preserve standalone operation and modular MSA/plugin use with CWL infrastructure.
- Require focused tests, docstrings for changed public Python surfaces, and `CHANGELOG.md` evidence.
- Allow release/version work only through a reviewed PR and existing release governance.

## Non-goals

- Weakening rulesets, dismissing valid reviews, fabricating status checks, or bypassing independent approval.
- Running multiple product-development agents concurrently.
- Broad repository rewrites, dependency churn, lockfile-only changes, or speculative architecture work.
- Performing irreversible external product actions from the agent.
- Claiming a valuation based only on repository activity. A USD 20 billion readiness claim requires independently verifiable product, reliability, security, adoption, retention, and revenue evidence.

## Architecture

### 1. Hourly orchestrator

A default-branch GitHub Actions workflow runs at minute 7 of every hour. It is fixed to `ContextualWisdomLab/naruon` and `develop`; runtime payloads cannot redirect it to another repository.

Every run dispatches the existing central workflows:

- `pr-review-fix-scheduler` for unresolved actionable review feedback and conflicted heads;
- `merge-scheduler` for current-head OpenCode/Strix review evidence, branch refresh, checks, approval, auto-merge, and direct merge when allowed.

The orchestrator then reads the live open PR count. It dispatches product development only when the count is exactly zero and no prior `autonomous/commercial-readiness-*` branch or PR is active.

### 2. Commercial-readiness development worker

A separate default-branch-only `repository_dispatch` workflow performs one bounded development slice.

Before editing, it validates all of the following against live GitHub metadata:

- target repository is exactly `ContextualWisdomLab/naruon`;
- base branch is exactly `develop`;
- no open pull request exists;
- no active autonomous commercial-readiness branch exists;
- the base SHA is a current 40-character commit SHA.

The worker checks out trusted automation from `ContextualWisdomLab/.github`, exchanges OIDC for a scoped OpenCode GitHub App token, clones the target base, and creates a unique branch.

It supplies OpenCode with trusted project context plus untrusted issue and commit summaries. The agent may choose exactly one gap. The prompt prioritizes:

1. email/context findability;
2. changing schedule truth and history;
3. buyer-visible reliability, security/privacy, accessibility, interoperability, packaging, observability, and evidence;
4. only then lower-impact maintainability work.

The agent cannot use shell, task delegation, external directories, or web tools. It may edit repository files but is instructed not to add dependencies, touch secrets, or modify workflows. External research-dependent work is deferred rather than guessed.

### 3. Deterministic validation and publication

After OpenCode edits, the workflow:

- restores temporary agent configuration;
- rejects workflow, secret, environment, generated, or oversized changes;
- requires a focused test change for code changes;
- requires `CHANGELOG.md` for product code changes;
- runs `git diff --check`;
- runs Python compilation, full backend Ruff, and the full backend pytest suite when backend code changed;
- runs frozen frontend install, lint, typecheck, tests, and production build when frontend code changed;
- refuses to publish when validation fails;
- rechecks that the base branch and PR queue did not move into an unsafe state;
- pushes only the unique branch and opens one non-draft PR with verification evidence;
- dispatches the central review and merge scheduler for that new PR.

No workflow writes to `develop` directly.

## Security and trust boundaries

- Both workflows load only from the central default branch.
- Manual `workflow_dispatch` is deliberately absent; privileged retries use typed `repository_dispatch` events.
- The hourly target is a compile-time constant, not user-controlled input.
- Repository and branch metadata are re-read before checkout, before push, and before PR creation.
- PR/issue text is treated as untrusted data inside delimited prompt sections.
- OpenCode receives no shell or web capability.
- Temporary `opencode.jsonc`, prompt files, and agent artifacts are restored or deleted before diff validation.
- The worker blocks modifications to `.github/workflows/**`, `.env*`, credentials, private keys, and agent-control files.
- Diff size and changed-file count are bounded to keep each slice reviewable.
- All merges remain subject to independent approval and required checks.

## Product and data constraints

- Naruon remains an email workspace that observes, synthesizes, and surfaces judgment-ready context.
- Human approval remains the terminal gate for irreversible actions.
- Database object names introduced by a slice must contain at least two words and use `snake_case` by default; CamelCase/PascalCase are acceptable where idiomatic.
- Public IDs must be opaque and non-sequential.
- Modules must work independently and as CWL/naruon plugins or services through explicit interfaces.
- Touched public Python surfaces require explanatory docstrings.
- Changed behavior requires focused regression tests; repository-wide required workflows remain the final evidence gate.

## Failure handling

- Scheduler dispatch failure fails the hourly run visibly.
- A non-zero PR queue suppresses product development but still runs fix/review/merge dispatches.
- An unsafe, ambiguous, or research-dependent gap yields no code change and no PR.
- Validation failure leaves no pushed branch.
- A base/head race aborts before push or PR creation.
- Existing open autonomous work suppresses duplicate development.
- Central merge scheduling retries in later hourly runs without weakening policy.

## Observability

Each hourly run writes a GitHub job summary containing:

- target repository and base branch;
- open PR count and numbers;
- dispatch results;
- whether development was skipped or dispatched;
- created development PR number when applicable.

Each development PR contains the selected buyer gap, scope boundaries, files changed, exact validation commands, and remaining risks.

## Acceptance criteria

1. A test proves the hourly workflow uses `7 * * * *` and has no `workflow_dispatch`.
2. A test proves the target repository and base branch are fixed.
3. A test proves both fix and merge schedulers are dispatched every hour.
4. A test proves development is dispatched only at zero open PRs.
5. A test proves the development worker revalidates zero open PRs and blocks duplicate autonomous branches.
6. A test proves direct writes to `develop`, workflow edits, secrets, and oversized diffs are rejected.
7. A test proves backend and frontend validation commands are present.
8. A test proves a successful slice opens one PR and immediately dispatches central review/merge processing.
9. Existing central workflow contract tests remain green.
10. The implementation is merged only after current-head required checks and independent approval succeed.
