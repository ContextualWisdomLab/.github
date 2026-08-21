# Hourly NVIDIA NIM Review-Autofix Boundary

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

Organization ruleset `18156473` now requires pull requests and blocks
non-fast-forward updates on every branch in the repositories it covers. The
repair worker therefore keeps its existing exact-head normal push as the first
publication attempt, but treats the specific GitHub `GH013` rejection containing
`Changes must be made through a pull request` as a change in publication mode,
not as permission to bypass the rule. It publishes the already validated commit
to a user-owned fork and opens an upstream stacked pull request whose base is the
original pull-request head branch. Any other push failure remains fatal.

The protected publication boundary is shared by ordinary review repair,
conflict repair, and clean auto-rebase. It re-reads the original open pull
request at the expected head before the direct attempt, after a rejected direct
attempt, and after creating the stacked pull request. Fork branches and stack
identities are deterministic and idempotent for one original PR head. Existing
fork repositories must be real forks of the target repository; an installation
token without a user-owned fork identity fails closed. Fork pull requests set
`maintainer_can_modify=false`, because GitHub warns that maintainer edits to a
fork branch containing Actions workflows can expose secrets. The stack still
requires ordinary checks, current-head reviews, independent approvals, resolved
threads, and a normal protected merge before it can update the original branch.

This decision was triggered by the observed `GH013` rejection on
`ContextualWisdomLab/contextual-orchestrator#765`; the compliant manual recovery
was `ContextualWisdomLab/contextual-orchestrator#810`. It replaces neither the
original PR nor its evidence. It only makes the repository rule itself the
publication mechanism, as GitHub documents for rulesets that require every
change to be associated with a pull request (GitHub, Inc., 2026a).

The write-capable scheduled pull-request autofix agent uses OpenCode with the
NVIDIA NIM API and the organization Actions secret `NVIDIA_NIM_API_KEY`. The
independent read-only review agent remains unchanged and continues to use its
existing credential and model-pool contract.

This separation is intentional. Review and repair have different privileges:
the review path publishes a verdict, while the autofix path may modify and push
a same-repository pull-request branch. Sharing or silently replacing the review
credential would couple two independent controls and weaken incident
containment.

## Central MSA ownership

`ContextualWisdomLab/.github` owns the scheduler, dispatch authorization,
model-provider configuration, credential binding, immutable worker source, and
fail-closed repair contract. Leaf repositories receive the behavior through the
central reusable workflow and do not copy provider credentials or scheduler
implementation.

The central scheduler runs once per hour, dispatches at most one repair per
invocation, and binds its implementation to the immutable called-workflow
source. Clearfolio owns only its small product caller. Naruon,
contextual-orchestrator, Inkspan, and other CWL services may adopt separate
callers while retaining standalone operation and the same central security
boundary.

## Immutable repository-dispatch worker source

`PR Review Autofix` is a default-branch-only `repository_dispatch` workflow.
GitHub defines `GITHUB_SHA` for `repository_dispatch` as the last commit on the
default branch and runs only a workflow file present on that branch. The
workflow therefore checks out its co-located context builder and policy source
at the exact workflow-run commit:

```yaml
repository: ContextualWisdomLab/.github
ref: ${{ github.sha }}
fetch-depth: 1
persist-credentials: false
```

Without the explicit `ref`, `actions/checkout` would resolve the repository's
moving default branch at checkout time. A later default-branch push could then
replace trusted scripts after GitHub had already selected the workflow run,
creating a time-of-check/time-of-use gap around a job that receives OIDC and
branch-write capability. CWE-367 classifies that race: a later default-branch
push must not replace privileged helpers after dispatch has already selected
the workflow revision (MITRE, 2026). The exact SHA keeps helper source
aligned with the workflow revision selected for dispatch.

The client payload remains untrusted metadata. It identifies a target only after
the worker re-reads live pull-request state and verifies the exact repository,
open state, same-repository branch, base ref and SHA, and head ref and SHA.

## Provider contract

The pinned OpenCode runtime enables only `nvidia-nim` through the
OpenAI-compatible adapter and NVIDIA hosted endpoint:

```text
https://integrate.api.nvidia.com/v1
```

The primary repair model is `mistralai/mistral-small-4-119b-2603`. The
`ci-autofix` agent and its model configuration both request high reasoning
through OpenCode's provider-option contract (`reasoningEffort: "high"`). NVIDIA's
Mistral Small 4 NIM API documents the corresponding request behavior as
`reasoning_effort: "high"`, which enables the model's reasoning mode. The small
model used for bounded helper work remains `nvidia/nemotron-3-nano-30b-a3b` and
is not a fallback provider. GitHub Models configuration, identifiers, base URLs,
and model-auth fallbacks are absent from the scheduled autofix execution path.

The high-reasoning setting is deliberate for write-capable review repair. This
workflow optimizes correctness, evidence quality, and controllability rather than
latency. It does not imply that deeper reasoning is universally superior; the
setting is an explicit operational choice for this bounded, security-sensitive
writer role and remains subject to exact-head regression evidence.

## Credential boundary

The organization secret is bound as:

```yaml
NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
```

It is present only on the two steps that execute OpenCode: ordinary
review-feedback repair and merge-conflict repair. Metadata collection,
checkout, context preparation, validation, commit, and push do not receive the
NVIDIA credential. A missing key is a fatal configuration error rather than a
signal to choose another provider.

The ordinary model execution step does not bind a GitHub write token. Its later
commit-and-push step may mutate only with `PR_REVIEW_MERGE_TOKEN`,
`OPENCODE_APPROVE_TOKEN`, or the short-lived OpenCode GitHub App token exchanged
from OIDC. The conflict-repair shell uses the same three mutation authorities
because the reviewed shell must re-read the live head and publish a verified
merge after model execution. Both mutation-capable paths evaluate an explicit
credential-availability guard before any Git write and fail closed when none of
those authorities exists. The workflow-generated `github.token` remains
read-only and is never accepted in a mutation credential expression.

Both model child processes run through:

```text
env -u GITHUB_TOKEN -u GH_TOKEN \
  -u ACTIONS_ID_TOKEN_REQUEST_TOKEN -u ACTIONS_ID_TOKEN_REQUEST_URL
```

The child receives the NVIDIA model credential and non-secret execution
controls, but cannot call GitHub APIs or mint an Actions OIDC token. GitHub
credentials remain available only to reviewed shell logic before or after the
child process. The key is never written to repository files, generated prompts,
command arguments, or ordinary logs.

## OpenCode repair sandbox

OpenCode permission rules use pattern matching and the last matching rule wins.
Both the global permission map and the named `ci-autofix` agent therefore allow
ordinary repository file edits first and then explicitly deny `.git` and
`.git/*`. The simple wildcard contract means the catch-all may match nested
paths, so the later Git-specific rules are required rather than descriptive
comments.

The worker also denies every non-file interaction unnecessary for bounded repair:

- `bash`;
- `task`;
- `skill`;
- `question`;
- `webfetch`;
- `websearch`;
- `lsp`;
- `external_directory`; and
- `doom_loop`.

The agent may read, search, list, and edit the validated same-repository PR
worktree. It receives an authoritative file allowlist derived from current
file-scoped actionable review context. An empty allowlist authorizes no change.
Review-thread text is untrusted authorization input, so paths beneath `.github/`
or `scripts/ci/` are categorically excluded from the ordinary review-derived
allowlist. A reviewer therefore cannot turn an inline comment on a workflow,
CODEOWNERS file, action, scheduler, or CI helper into permission for the
autonomous writer to modify its own control plane. Such changes require a
separately scoped, independently reviewed control-plane change rather than the
review-autofix path.

The shell independently syntax-checks changed Python, validates changed workflow
files when `actionlint` is present, rechecks the live head, and refuses unresolved
merge markers.

## Exact ordinary and conflict repair write boundary

The ordinary and conflict repair modes use the same fail-closed model-write
boundary. This closes a prior asymmetry in which conflict repair had a complete
snapshot while ordinary repair depended only on a later visible Git diff.

Before either model process starts, the worker creates:

1. a NUL-delimited authoritative allowlist of exact paths; and
2. a deterministic snapshot of the complete pre-model worktree, including ignored paths,
   tracked paths, non-ignored untracked paths, file modes, regular-file SHA-256
   values, sizes, and symbolic-link targets.

For conflict repair, Git supplies the allowlist through `git diff --name-only -z
--diff-filter=U`. For ordinary repair, the context builder supplies current-head
file-scoped actionable paths after rejecting control-plane paths beneath
`.github/` and `scripts/ci/`; the workflow converts the remaining paths to a
sorted NUL-delimited file. In both cases, temporary OpenCode configuration is
installed only after the snapshot and restored before verification.

The trusted helper calls a fixed validated `/usr/bin/git`. Git's official
`git-ls-files` contract is used twice: cached plus non-ignored other paths form
the reviewable inventory, while `--others --ignored --exclude-standard` adds the
ignored-path inventory. Combining both results prevents model-created cache,
credential, build-output, or other ignored paths from escaping comparison merely
because a later `git add -A` would normally omit them.

The helper refuses noncanonical roots and paths, a repository root whose
immediate parent is a symbolic link, oversized inventories, malformed
snapshot documents, unrecognized fingerprint schemas, and allowlist paths absent
from the pre-model snapshot. Every symlink must resolve to a regular file inside
the repository whose target is present in the reviewable Git inventory.
External, ignored-target, dangling, directory-backed, and metadata-race links
fail closed with bounded diagnostics that do not expose private filesystem
exceptions.

After OpenCode exits, the workflow restores any prior repository configuration
and compares the current inventory with the snapshot. Created, deleted,
modified, mode-changed, retargeted, ignored, dangling, directory-backed,
external-link, metadata-race, or other out-of-scope writes reject the run before
staging. Verification is not replaced by the ordinary later diff check; both
remain independent defenses.

## Git metadata, hooks, and push destination

Model-editable repository state must not control the privileged publication
step. Both OpenCode permission objects deny `.git` and `.git/*`, but the reviewed
shell also treats permission enforcement as defense in depth rather than proof.
The full snapshot detects out-of-scope worktree changes, and every privileged
commit and push invokes Git with `core.hooksPath=/dev/null`.

Git documents that hooks can execute at commit and push lifecycle points and that
`core.hooksPath` selects their directory. Disabling hooks for these two commands
prevents a repository-provided or model-created hook from executing with the
post-model GitHub credential. The worker still performs explicit syntax,
allowlist, marker, and live-head checks; hook suppression does not weaken those
gates.

Before push, the worker reconstructs an explicit revalidated repository URL from
`GITHUB_SERVER_URL` and the exact live `TARGET_REPOSITORY`. It supplies that URL
directly to `git push` instead of trusting model-mutable Git metadata such as
`remote.origin.url` or a push URL. The branch ref and exact head are validated
again immediately before publication.

After a successful Git transport push, the PR API can briefly retain the old
head even though the live branch already points at the new commit. The helper
retries only that exact head-mismatch result five times at one-second intervals;
closed PRs, changed repositories/branches, malformed responses, and a mismatch
that survives the bound still fail closed. This contract was added after a
successful exact-head push to `contextual-orchestrator#773` was initially
reported as failed by the stale PR response.

When that explicit push receives the exact PR-required `GH013` response, the
same trusted helper uses GitHub CLI's documented user-fork and explicit
`owner:branch` pull-request semantics (GitHub CLI, 2026a, 2026b). The Git token
is supplied to Git through an environment-only HTTP authorization header rather
than a remote URL or command argument. The fork branch is never force-pushed;
closed or divergent prior publication branches receive a new exact-output
suffix. A live matching stacked pull request is reused rather than duplicated.

The repair worker cannot approve its own changes, lower branch protection,
reinterpret queued or failed checks, manufacture independent review, merge a PR,
or publish a release. Those decisions remain with separate protected workflows
and repository policy.

## Independent review-agent boundary

`.github/workflows/opencode-review-dispatch.yml` is not modified by this slice.
The regression contract pins that workflow's Git blob SHA byte-for-byte rather
than inferring independence from provider-name strings. The existing reviewer
retains its own separately reviewed identity, model pool, and credential chain.

This is a control separation, not naming convention. Review produces a verdict
that may gate merge; autofix proposes branch changes. Their credentials,
workflow sources, and change histories remain independent.

## Test-first evidence

The ordinary write-scope defects were captured before production repair:

- RED exact head `6db97138f93869d04bfac0aba935844323b20b50`;
- focused run `31149695625` failed exactly the three new contracts for ordinary
  snapshot verification, Git-control-file and hook isolation, and explicit push
  destination while the pre-existing tests remained green;
- production repair began at
  `3e124301cc27e04f9f4d4daf079bc8cd32fa9757`;
- the ordering regression was corrected without weakening the conflict boundary
  at `b68c85cec8c14e226bf31e299571541826d89f50`; and
- documentation RED head `3b0e3a9c8f17032b57263d162e52dfd3f239fa4b`
  and run `31150267219` failed only the new public-record contract while 72
  focused tests and complete production statement and branch coverage remained
  green.

A later Strix security review found that the review-derived allowlist still
accepted control-plane paths. The finding was reproduced test-first at
`4ab7693ae2fe5ed93c59ca84f93a757bed1477bd` with a regression covering workflows,
actions, CODEOWNERS, and CI helpers. Production head
`a8b7663580bba108a6d2186658b5acae478d2fc8` then rejected `.github/` and
`scripts/ci/` paths while retaining ordinary product-source repair. Its focused
quality run executed 1,075 tests plus 16 subtests and measured 100% statement and
branch coverage for both autofix production helpers, with 100% public docstrings.
That exact-head evidence is historical after any later documentation commit and
must be re-established on the new current head.

The later writer-model and mutation-authority hardening was likewise captured by
permanent RED contracts before the implementation changed. Those contracts pin
the exact NVIDIA Mistral Small 4 writer, high reasoning, absence of the obsolete
Mistral Nemotron identifier, explicit mutation credentials, and guards that run
before any Git write. Predecessor-head successes are historical TDD evidence,
not merge evidence. The final integrated head must establish every required
quality, security, review, and protection gate again.

## Verification contract

Automated tests prove:

1. the caller retains its approved one-hour cadence;
2. OpenCode enables only NVIDIA NIM, uses the exact Mistral Small 4 writer with
   high reasoning, and receives the model key only in its two execution steps;
3. missing model credentials fail closed and model children receive no GitHub or
   OIDC write credential;
4. mutation-capable ordinary and conflict paths accept only established explicit
   secrets or the exchanged OpenCode app token, never `github.token`, and fail
   closed before Git writes when no mutation authority exists;
5. trusted helper source is checked out at the immutable workflow-run SHA;
6. ordinary review-thread authorization rejects `.github/` and `scripts/ci/`
   control-plane paths before producing the sealed allowlist;
7. ordinary and conflict repair both snapshot before model execution and verify
   after temporary configuration restoration but before staging;
8. tracked, untracked, and ignored-path inventories, symlink targets, mode
   changes, deletions, creations, and metadata races are covered;
9. both OpenCode permission maps deny `.git` and `.git/*` after the catch-all
   edit rule;
10. every privileged commit and push disables repository hooks through
   `core.hooksPath=/dev/null`;
11. every push uses the explicit target URL and never model-mutable `origin`;
12. the independent review workflow retains its exact reviewed Git blob SHA;
13. the production helper retains 100% statement and branch coverage and 100%
    public docstrings; and
14. exact-current-head security, automated review, independent approval,
    unresolved-thread, and branch-protection gates pass before merge.
15. only the exact PR-required `GH013` response can activate fork-backed
    publication; unrelated failures, head drift, repository-name collisions,
    unavailable user identity, and malformed GitHub responses fail closed.
16. a successful direct push tolerates only bounded old-head PR API lag and
    never treats another identity or a persistent mismatch as publication.

## Scheduling and activation

The NVIDIA worker does not create a second repair scheduler. It is consumed by
the hourly central review-fix scheduler and product caller. Scheduled workflows
run only from the protected default branch, so feature-branch checks do not make
the heartbeat active. Activation requires protected integration and accepted-main
verification.

## Rollback

Rollback must revert the NVIDIA transport, ordinary and conflict repair scope
contracts, review-derived control-plane path exclusion, `.git` denial, ignored-path
inventory, hook suppression, explicit push destination, tests, operator guidance,
doctoring, and changelog as one reviewed change. A partial rollback that restores
review-thread authority over `.github/` or `scripts/ci/`, ordinary diff-only
validation, model-mutable Git metadata, repository hooks, GitHub-token model
authentication, or a mutable helper checkout is unsafe.

If NVIDIA NIM is unavailable, scheduled repair must fail closed while read-only
review, required checks, manual maintenance, and protected merge policy remain
available. Rollback is not permission to bypass independent approval or release
gates.

## References

GitHub CLI. (2026a). *gh pr create*. Retrieved August 21, 2026, from
https://cli.github.com/manual/gh_pr_create

GitHub CLI. (2026b). *gh repo fork*. Retrieved August 21, 2026, from
https://cli.github.com/manual/gh_repo_fork

GitHub, Inc. (2026a). *Available rules for rulesets*. Retrieved August 21,
2026, from
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets

GitHub, Inc. (2026b). *Creating a pull request from a fork*. Retrieved August
21, 2026, from
https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request-from-a-fork

Git Project. (2026). *git-ls-files*. Retrieved August 7, 2026, from
https://git-scm.com/docs/git-ls-files

Git Project. (2026). *githooks*. Retrieved August 7, 2026, from
https://git-scm.com/docs/githooks

MITRE. (2026). *CWE-367: Time-of-check time-of-use (TOCTOU) race condition*.
https://cwe.mitre.org/data/definitions/367.html

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 7, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub, Inc. (n.d.-b). *Secrets reference*. GitHub Docs. Retrieved August 7,
2026, from https://docs.github.com/en/actions/reference/security/secrets

NVIDIA Corporation. (n.d.-a). *LLM APIs*. NVIDIA API Catalog. Retrieved August
7, 2026, from https://docs.api.nvidia.com/nim/reference/llm-apis

NVIDIA Corporation. (2026). *Query the Mistral-Small-4-119B-2603 API*. NVIDIA
NIM for Vision Language Models. Retrieved August 8, 2026, from
https://docs.nvidia.com/nim/vision-language-models/1.7.0/examples/mistral-small-4-119b-2603/api.html

NVIDIA Corporation. (n.d.-c). *NVIDIA / nemotron-3-nano-30b-a3b*. NVIDIA API
Catalog. Retrieved August 7, 2026, from
https://docs.api.nvidia.com/nim/re/reference/nvidia-nemotron-3-nano-30b-a3b

OpenCode. (2026a). *Permissions*. https://opencode.ai/docs/permissions

OpenCode. (2026b, July 28). *Providers*. https://opencode.ai/docs/providers

OpenCode. (2026c). *Agents*. Retrieved August 8, 2026, from
https://opencode.ai/docs/agents

OpenCode. (2026d). *Models*. Retrieved August 8, 2026, from
https://opencode.ai/docs/models
