# Hourly PR review-repair scheduler

The central automation separates **product cadence** from the **reusable repair
engine**.

- `clearfolio-hourly-review-repair.yml` owns Clearfolio's heartbeat at minute 23
  of every hour.
- `naruon-hourly-review-repair.yml` owns naruon's platform heartbeat at minute 11
  of every hour against protected `develop`.
- `pr-review-fix-scheduler.yml` is the reusable, product-neutral scheduler
  module. It has no product-specific timer and can be called by naruon,
  contextual-orchestrator, Inkspan, or another CWL service with an explicit
  repository and base branch.
- `pr-review-autofix.yml` is the bounded write-capable worker. It uses OpenCode
  with NVIDIA NIM and does not approve or merge pull requests.

Merge eligibility remains owned by the separate merge scheduler, branch
protection, required checks, independent review, and unresolved-thread policy.
The repair worker proposes changes only; it cannot reinterpret queued or failed
checks as success.

## Clearfolio execution contract

The default Clearfolio caller provides the following immutable operating
parameters to the reusable scheduler:

```yaml
target_repository: ContextualWisdomLab/clearfolio
base_branch: main
max_prs: "50"
max_dispatches: "1"
retry_hours: "1"
```

The scheduled heartbeat is `23 * * * *`. Repository-scoped concurrency and
`cancel-in-progress: true` ensure that a superseded Clearfolio queue scan does
not overlap its successor. At most one repair dispatch is created per run.

The caller passes only the established `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN` scheduler credentials. It does not receive or forward
`NVIDIA_NIM_API_KEY`; the model credential is scoped exclusively to the two
OpenCode execution steps in the separately reviewed autofix worker.

## naruon execution contract

The naruon caller provides the following immutable operating parameters:

```yaml
target_repository: ContextualWisdomLab/naruon
base_branch: develop
max_prs: "50"
max_dispatches: "1"
retry_hours: "2"
```

The scheduled heartbeat is `11 * * * *`. The caller job grants `id-token: write`
so the reusable NVIDIA NIM scheduler can mint its OpenCode App fallback from
GitHub OIDC. It does not receive or forward `NVIDIA_NIM_API_KEY` and never
introduces `COPILOT_GITHUB_TOKEN`.

The caller passes only the established `PR_REVIEW_MERGE_TOKEN` and
`OPENCODE_APPROVE_TOKEN` scheduler credentials. It does not receive or forward
`NVIDIA_NIM_API_KEY`; the model credential is scoped exclusively to the two
OpenCode execution steps in the separately reviewed autofix worker.

## Reusable target-selection contract

The shared scheduler resolves its target in this order:

1. `repository_dispatch` payload `target_repository`;
2. reusable-workflow input `target_repository`;
3. repository variable `PR_REVIEW_FIX_TARGET_REPOSITORY`; and
4. the repository in which the scheduler executes.

This ordering keeps standalone operation possible while preventing the central
module from silently hard-coding one product. Clearfolio's product-specific
choice is visible in its dedicated caller. A sibling service can add its own
small caller or invoke the reusable workflow directly without copying the
scheduler implementation, OpenCode configuration, or model credentials.

`canonical_ref` remains an accepted deprecated input only so callers pinned to
older workflow interfaces can upgrade without a coordinated breaking change.
It is never read and cannot choose executable scheduler code.

## Immutable reusable-workflow source

GitHub associates the ordinary `github` context in a reusable workflow with the
caller. Consequently, a privileged called workflow must not use caller-derived
`github.sha`, a caller payload, or a mutable branch such as `main` to select its
co-located implementation.

The checkout step instead uses:

```yaml
repository: ${{ job.workflow_repository }}
ref: ${{ job.workflow_sha }}
```

`job.workflow_repository` identifies the repository that contains the called
workflow and `job.workflow_sha` identifies its immutable resolved commit. The
workflow validates repository, SHA, workflow ref, and file path before checkout,
then verifies the resulting Git revision before executing the scheduler helper.
Checkout credentials are not persisted.

The later repository-dispatch worker similarly checks out trusted central helper
source at `${{ github.sha }}`. The dispatch payload does not select executable
worker code.

## Exact model write scope

Ordinary and conflict repair use the same fail-closed worktree comparison. The
worker snapshots the complete pre-model repository through the trusted central
helper, including ignored paths, tracked files, other untracked files, file modes,
regular-file hashes, and symbolic-link targets. It then verifies the complete
post-model inventory after temporary OpenCode configuration is restored and
before any stage, commit, or push.

The authoritative allowlist is NUL-delimited. Ordinary repair receives only
current-head file-scoped actionable review paths. Conflict repair receives only
Git's exact unresolved paths from `git diff --name-only -z --diff-filter=U`.
An empty ordinary allowlist authorizes no changes.

The verifier rejects created, deleted, modified, mode-changed, retargeted,
ignored, dangling, directory-backed, external-link, metadata-race, and other
out-of-scope paths. It invokes a fixed validated `/usr/bin/git`, bounds path and
inventory sizes, and emits redacted static failures for filesystem races. A
symlink target must be a regular in-repository path present in the reviewable Git
inventory.

Both OpenCode permission objects allow ordinary file repair but explicitly deny
`.git` and `.git/*`. Model child processes also receive neither GitHub write
credentials nor Actions OIDC request credentials. These permission controls are
defense in depth; the complete pre/post snapshot remains authoritative.

## RCA and remediation-feasibility gate

Every failed check, unresolved actionable review, merge conflict, or scheduler
error is first treated as evidence to diagnose, not as a reason to guess at a
patch. Before editing, the worker establishes the root cause from the exact
current PR head and base, then lists the smallest plausible remediation
candidates.

A candidate is feasible only when all of the following are true:

- the current worker has repository-writer authority for the target repository;
- every required edit is inside the sealed allowed paths;
- credential and protected-setting requirements can be satisfied without
  weakening branch protection, tests, review independence, or secret isolation;
- stack and dependency order permit the change on the current branch;
- a focused test or exact-head check can verify the result; and
- the action actually changes the root cause rather than only restating the
  blocker, rerunning unchanged evidence, or manufacturing a passing status.

The worker implements only the smallest candidate that passes this gate. When no
repository edit is feasible within the worker's authority, it leaves the tree
unchanged and records the concrete failed feasibility condition. The parent queue scan must then continue with the next eligible bounded PR or buyer-visible product gap instead of ending the productive portion of the hourly run.

Queued reviews or checks remain merge blockers, but their latency does not make
an unrelated code edit realistic. The scheduler may inspect another independent
PR, strengthen non-conflicting tests or documentation, or select one bounded
product slice; it must not claim an external approval, runner capacity, billing
change, or protected-setting mutation that it cannot actually perform.

## Privileged Git publication

Every reviewed commit and push runs with `core.hooksPath=/dev/null`, preventing a
repository hook from executing after model work with the privileged GitHub
credential. This does not replace syntax, allowlist, merge-marker, exact-head, or
branch-protection checks.

Before publication, the worker re-reads the live PR head. It reconstructs an
explicit revalidated repository URL from `GITHUB_SERVER_URL` and the exact target
repository and supplies that URL directly to `git push`. It never trusts
model-mutable `origin`, `remote.origin.url`, push URLs, aliases, or hooks as the
publication destination.

A head movement, unresolved marker, missing merge state, out-of-scope write,
malformed repository identity, absent model credential, or failed validation
terminates the run without publication. A successful push creates a new head
that must be reviewed and checked again; the worker does not synthesize approval.

## Security and MSA boundary

The scheduler may inspect review state and dispatch the already-reviewed bounded
autofix workflow. It cannot approve its own changes, lower branch protection,
convert queued checks to success, publish releases, or bypass independent
review. Product repositories remain independently operable and consume the
central policy as a reusable module rather than copying privileged automation.

Clearfolio, naruon, contextual-orchestrator, Inkspan, and other CWL services
retain their own product tests, authorization, release, deployment,
data-governance, and runtime responsibilities. The central workflow owns only
organization-level queue inspection and bounded repair dispatch.

## Operator procedure

When a scheduled run fails, classify the result before rerunning:

- no actionable file-scoped feedback: expected no-op;
- missing `NVIDIA_NIM_API_KEY`: central secret configuration failure;
- head changed: safe optimistic-concurrency refusal; inspect the new head rather
  than retrying predecessor evidence;
- out-of-scope or ignored-path change: treat as a security failure and preserve
  the failed exact-head evidence;
- invalid symlink or metadata race: inspect the repository path without exposing
  private runner exceptions;
- model timeout or provider failure: do not treat it as review, approval, or
  check success; and
- push or branch-protection refusal: retain the branch unchanged and resolve the
  GitHub policy or credential cause independently.

Never add a one-shot write workflow to repair this worker. Apply reviewed source
changes directly to the exact branch head, rerun focused contracts, then rerun
all required security and review gates.

## Verification

Permanent tests prove:

- the Clearfolio caller owns exactly one hourly schedule and names the exact
  repository and protected base branch;
- the shared scheduler contains no product-specific timer or repository name;
- the dispatch budget and same-head retry floor remain one;
- caller and reusable-workflow secrets are explicit and never use
  `secrets: inherit`;
- immutable source, NVIDIA-only model authentication, child-process credential
  stripping, live-head guards, and independent reviewer identity remain intact;
- ordinary and conflict repair share the complete ignored-inclusive snapshot and
  NUL-delimited allowlist boundary;
- the RCA and remediation-feasibility gate prevents speculative or
  authority-incompatible edits while allowing the queue to continue productive
  non-conflicting work;
- `.git` edits, repository hooks, and model-mutable push destinations cannot
  control privileged publication; and
- the production verifier retains 100% statement and branch coverage and 100%
  public docstrings.

Every exact PR head must also pass all central security, workflow-contract,
automated-review, independent-review, unresolved-thread, and branch-protection
gates before merge.

## References (APA 7th edition)

Git Project. (2026). *git-ls-files*. Retrieved August 7, 2026, from
https://git-scm.com/docs/git-ls-files

Git Project. (2026). *githooks*. Retrieved August 7, 2026, from
https://git-scm.com/docs/githooks

GitHub, Inc. (n.d.-a). *Contexts reference: Job context*. GitHub Docs. Retrieved
August 7, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/contexts#job-context

GitHub, Inc. (n.d.-b). *Events that trigger workflows*. GitHub Docs. Retrieved
August 7, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.-c). *Reusing workflows*. GitHub Docs. Retrieved August 7,
2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/how-tos/reuse-automations/reuse-workflows

OpenCode. (2026). *Permissions*. https://opencode.ai/docs/permissions
