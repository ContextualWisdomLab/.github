# Contextual Orchestrator Review-Autofix Boundary

## Decision

The write-capable scheduled pull-request autofix agent uses OpenCode through
the organization contextual-orchestrator gateway. The gateway URL is an
Actions variable, its bearer token is an Actions secret, and upstream provider
credentials remain in the gateway's KV registry. The gateway starts with
automatic model discovery and selects the provider model; the worker never
receives raw NVIDIA NIM, OpenAI, OpenRouter, or Bytez provider keys.

The independent read-only review agent remains unchanged and keeps its existing
credential and model-pool contract. Review and repair have different
privileges: the review path publishes a verdict, while the autofix path may
modify and push a same-repository pull-request branch.

## Central MSA ownership

`ContextualWisdomLab/.github` owns scheduler dispatch authorization, gateway
configuration, credential binding, immutable worker source, and the fail-closed
repair contract. Leaf repositories consume the reusable workflow and do not
copy provider credentials or scheduler implementation.

## Provider and tool-loop contract

The generated OpenCode configuration enables only
`contextual-orchestrator/contextual-orchestrator` and points at
`CONTEXTUAL_ORCHESTRATOR_BASE_URL`. It sends the explicit
`X-Contextual-Orchestrator-Tool-Loop: v1` header so OpenCode owns the bounded
function-call loop while the gateway owns provider selection. Streaming tool
loops fail closed until the gateway exposes a shape-preserving streaming relay.

The gateway's `--auto-discover-model-agents` process resolves registered
provider credentials from its KV registry and excludes unavailable providers.
No provider key is copied into the repository, generated OpenCode config,
prompt, command argument, or ordinary worker log. Missing gateway URL/token
configuration fails closed before model execution.

## Immutable repository-dispatch worker source

`PR Review Autofix` is a default-branch-only `repository_dispatch` workflow. It
checks out central helper source at the exact workflow-run SHA with
`persist-credentials: false`, then validates the target PR's live repository,
open state, same-repository branch, base ref/SHA, and head ref/SHA before any
model or write operation.

## Exact ordinary and conflict repair write scope

Ordinary and conflict repair share the complete pre/post worktree snapshot,
including ignored paths, file modes, regular-file hashes, and symbolic-link
targets. The ordinary allowlist is NUL-delimited and derived from current-head
file-scoped actionable review context; conflict repair uses Git's exact
unresolved paths. The verifier rejects out-of-scope, ignored, dangling,
external, metadata-race, and Git-control-file changes.

Both OpenCode permission maps allow reviewed repository file edits but deny
`.git` and `.git/*`, as well as shell, web, task, and external-directory
interactions. Privileged commits and pushes use `core.hooksPath=/dev/null` and
an explicit revalidated repository URL. Child processes receive no GitHub or
Actions OIDC write credentials.

## RCA, approval, and rollback

The worker establishes exact-head root-cause analysis and remediation
feasibility before editing. Queued, pending, stale, failed, or synthetic check
evidence never becomes success. The worker cannot approve, merge, lower branch
protection, change reviewer identity, or turn an external gateway failure into
a repository edit. Every pushed head must be reviewed and checked again.

Rollback is a reviewed source change. It must preserve ordinary and conflict
repair scope, review-derived control-plane path exclusion, `.git` denial,
ignored-path inventory, hook suppression, explicit push destination, gateway
authentication, and independent approval.

## Verification

The focused quality workflow checks the gateway-only provider, explicit
tool-loop header, URL/token scope to the two OpenCode steps, child-process
credential stripping, immutable source pin, exact write scope, and unchanged
independent review-agent workflow. It also retains 100% statement/branch and
public-docstring gates for the trusted helpers.

## APA 7th references

Git Project. (2026). *git-ls-files*. Retrieved August 20, 2026, from
https://git-scm.com/docs/git-ls-files

Git Project. (2026). *githooks*. Retrieved August 20, 2026, from
https://git-scm.com/docs/githooks

GitHub. (n.d.). *Secrets reference*. Retrieved August 20, 2026, from
https://docs.github.com/en/actions/reference/security/secrets

OpenCode. (n.d.). *Permissions*. Retrieved August 20, 2026, from
https://opencode.ai/docs/permissions

ContextualWisdomLab. (2026). *Contextual-orchestrator gateway-only provider
contract and automatic model discovery* [Internal architecture records].
