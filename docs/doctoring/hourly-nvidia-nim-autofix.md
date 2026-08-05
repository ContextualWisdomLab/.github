# Hourly NVIDIA NIM Review-Autofix Boundary

## Decision

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

The central scheduler established by the baseline repair runs once per hour,
dispatches at most one repair per invocation, and binds its scheduler
implementation to the immutable called-workflow source. The NVIDIA migration
changes only the model transport used by the write-capable autofix worker and
hardens that worker's own default-branch source checkout.

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
branch-write capability. The explicit SHA keeps the executed helper source
aligned with the workflow revision selected for the dispatch.

The client payload remains untrusted metadata. It can identify the intended
target PR only after the workflow re-reads live PR state and verifies exact base
and head refs and SHAs.

## Provider contract

The pinned OpenCode runtime is configured with one enabled provider,
`nvidia-nim`, using the OpenAI-compatible adapter and NVIDIA hosted endpoint:

```text
https://integrate.api.nvidia.com/v1
```

The primary repair model is `mistralai/mistral-nemotron`; the small model used
for bounded helper work is `nvidia/nemotron-3-nano-30b-a3b`. NVIDIA documents
both identifiers. Mistral-Nemotron supports tool calling for agentic workflows.
Nemotron 3 Nano is used as a lower-active-parameter reasoning helper, not as a
fallback provider.

Only the `nvidia-nim` provider is enabled. GitHub Models configuration, model
identifiers, base URLs, and model-auth fallbacks are absent from the scheduled
autofix execution path.

## Credential boundary

The organization secret is bound as:

```yaml
NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
```

It is present only on the two steps that execute OpenCode: ordinary
review-feedback repair and merge-conflict repair. Earlier metadata collection,
checkout, context preparation, validation, commit, and push steps do not receive
the NVIDIA credential.

The workflow passes the key through an environment variable and OpenCode
substitutes `{env:NVIDIA_API_KEY}` into provider configuration. The key is never
written to repository files, command arguments, generated prompts, or logs. A
missing secret is a fatal configuration error; the workflow does not fall back
to `GITHUB_TOKEN`, a GitHub Models token, or another provider.

The ordinary repair step no longer binds a GitHub write token at step scope. The
conflict-repair shell retains GitHub credentials because the same shell must
re-read the live PR and push a verified merge result after model execution. In
both paths, the OpenCode child process is launched through:

```text
env -u GITHUB_TOKEN -u GH_TOKEN \
  -u ACTIONS_ID_TOKEN_REQUEST_TOKEN -u ACTIONS_ID_TOKEN_REQUEST_URL
```

Consequently, model-controlled file operations receive the NVIDIA model
credential and non-secret execution controls, but cannot call GitHub APIs or
mint an OIDC token. GitHub credentials remain available only to reviewed shell
logic before or after the child process. This reduces the consequence of prompt
injection without removing the worker's independently validated branch-update
capability.

GitHub documents that a missing secret expression resolves to an empty string
and recommends delivering secrets through inputs or environment variables rather
than embedding them in command lines. The explicit preflight prevents an
ambiguous unauthenticated provider request and preserves fail-closed behavior.

## OpenCode repair sandbox

OpenCode permissions are permissive unless explicitly restricted. The workflow
therefore denies every non-file interaction that is unnecessary for a bounded
review repair in both the global permission map and the named `ci-autofix`
agent:

- `bash`
- `task`
- `skill`
- `question`
- `webfetch`
- `websearch`
- `lsp`
- `external_directory`
- `doom_loop`

The agent may read, search, list, and edit only the validated same-repository PR
worktree. It receives an authoritative file allowlist derived from current
file-scoped actionable review context. The workflow rejects any changed path
outside that allowlist, syntax-checks changed Python, validates workflow files
when `actionlint` is available, rechecks the live head before push, and refuses
to publish unresolved merge markers.

Explicitly denying `skill`, `question`, and `doom_loop` matters for unattended
execution. OpenCode exposes these as independent permissions; omitted
permissions are not implicitly denied. The worker must not load a broader skill,
pause for interactive approval, or repeat an identical tool action beyond the
bounded workflow contract.


## Conflict-resolution model write boundary

A merge-conflict repair begins by merging the exact validated base SHA into
the exact PR head. Immediately after Git records the unresolved paths, the
worker writes two immutable local inputs before OpenCode receives the task:

1. a NUL-delimited allowlist produced by `git diff --name-only -z
   --diff-filter=U`; and
2. a deterministic snapshot of every tracked and non-ignored untracked
   worktree path after the base merge.

The snapshot fingerprints regular-file content with SHA-256 and records file
size, mode, symbolic-link target, deletion, and other entry types. This timing
is deliberate: legitimate non-conflict changes introduced by the base merge
are part of the pre-model baseline, while changes made later by the model are
not.

After OpenCode exits, the workflow restores the repository's prior OpenCode
configuration and compares the current worktree to that pre-model snapshot.
Only paths in Git's NUL-delimited conflict allowlist may differ. A created,
deleted, modified, mode-changed, or retargeted path outside that set fails the
job before `git add -A`, commit, or push. Path inventories and path byte
lengths are bounded, malformed snapshot data fails closed, and diagnostic
output JSON-escapes path names rather than emitting them as workflow commands.

Ignored build caches are outside the comparison because `git add -A` does not
publish them. Git metadata is outside the model's file-edit surface; the
model process has no shell, GitHub token, or Actions OIDC credential. The
later live-head, unresolved-marker, merge-tree, syntax, and push checks remain
independent defenses.

## GitHub write boundary

The model transport change does not expand GitHub permissions. GitHub repository
credentials and the NVIDIA model credential remain separate. The existing
short-lived GitHub App/OIDC exchange and branch-write token chain are not used
for model authentication. Conversely, `NVIDIA_NIM_API_KEY` is not used for
GitHub reads or writes.

Before editing, the workflow validates repository syntax, numeric PR identity,
forty-character base and head SHAs, same-repository branch ownership, open PR
state, and exact live base/head metadata. Before pushing, it re-reads the live
head and fails if the branch moved. The scheduler and worker cannot approve
their own changes, lower branch protection, convert queued checks into success,
or publish a release.

## Independent review-agent boundary

`.github/workflows/opencode-review-dispatch.yml` is not modified by this
migration. The regression contract pins that workflow's Git blob SHA
byte-for-byte rather than inferring independence from provider-name strings.
This allows the existing reviewer to retain its own evolving, separately
reviewed model-pool and credential design while proving that this autofix change
did not alter it.

This is not cosmetic separation: review produces the verdict that gates merge,
whereas autofix proposes branch changes. Keeping their credentials, workflow
sources, and change histories independent limits the blast radius of either
path.

## Verification contract

Automated tests must prove all of the following:

1. The repair scheduler retains the approved hourly cron expression.
2. The OpenCode configuration enables only `nvidia-nim`.
3. Primary and small model identifiers match NVIDIA's published identifiers.
4. The provider uses the OpenAI-compatible package, NVIDIA base URL, and
   environment substitution.
5. Exactly two OpenCode execution steps receive `NVIDIA_API_KEY` from
   `secrets.NVIDIA_NIM_API_KEY`.
6. GitHub Models credentials, providers, model identifiers, base URLs, and
   `USE_GITHUB_TOKEN` model-auth fallback are absent from the autofix workflow.
7. The trusted autofix checkout is pinned to `${{ github.sha }}`, does not use
   mutable `main`, and does not persist credentials.
8. Both OpenCode permission maps explicitly deny every non-file interaction
   listed in the sandbox section.
9. Both OpenCode subprocesses explicitly remove GitHub and OIDC credentials;
   the ordinary model step has no step-level GitHub token binding.
10. The independent review workflow retains its exact reviewed Git blob SHA and
    contains no coupling to the autofix event.
11. A missing NVIDIA secret fails before either model process executes.
12. The exact current head passes complete workflow, Python, security,
    CodeRabbit, independent-review, unresolved-thread, and branch-protection
    gates before merge.

## Scheduling and activation

The NVIDIA worker does not create a second scheduler. It is consumed by the
hourly central review-fix scheduler established in the stacked baseline PR. The
hourly production loop becomes active only after both the baseline and this
migration are merged into the protected default branch. Draft or feature-branch
workflow files are not represented as active organization automation.

## Rollback

Rollback is a normal revert of the NVIDIA transport commit. A rollback must not
reintroduce an implicit GitHub-token model-auth fallback, GitHub or OIDC
credentials inside the model child process, a mutable trusted source checkout,
permissive unattended-agent tools, or any change to the independent review-agent
credential system. If NVIDIA NIM is unavailable, scheduled autofix must fail
closed while review, checks, and manual maintenance remain available.

## References

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved
August 4, 2026, from
https://docs.github.com/en/enterprise-cloud@latest/actions/reference/workflows-and-actions/events-that-trigger-workflows

GitHub, Inc. (n.d.-b). *Secrets reference*. GitHub Docs. Retrieved August 4,
2026, from https://docs.github.com/en/actions/reference/security/secrets

NVIDIA Corporation. (n.d.-a). *LLM APIs*. NVIDIA API Catalog. Retrieved August
4, 2026, from https://docs.api.nvidia.com/nim/reference/llm-apis

NVIDIA Corporation. (n.d.-b). *Mistralai / mistral-nemotron*. NVIDIA API
Catalog. Retrieved August 4, 2026, from
https://docs.api.nvidia.com/nim/reference/mistralai-mistral-nemotron

NVIDIA Corporation. (n.d.-c). *NVIDIA / nemotron-3-nano-30b-a3b*. NVIDIA API
Catalog. Retrieved August 4, 2026, from
https://docs.api.nvidia.com/nim/re/reference/nvidia-nemotron-3-nano-30b-a3b

OpenCode. (2026a). *Permissions*. https://opencode.ai/docs/permissions

OpenCode. (2026b, July 28). *Providers*. https://opencode.ai/docs/providers
