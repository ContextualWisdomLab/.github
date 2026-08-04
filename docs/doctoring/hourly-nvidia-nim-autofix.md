# Hourly NVIDIA NIM Review-Autofix Boundary

## Decision

The write-capable scheduled pull-request autofix agent uses OpenCode with the NVIDIA NIM API and the organization Actions secret `NVIDIA_NIM_API_KEY`. The independent read-only review agent remains unchanged and continues to use its existing credential and model-pool contract.

This separation is intentional. Review and repair have different privileges: the review path publishes a verdict, while the autofix path may modify and push a same-repository pull-request branch. Sharing or silently replacing the review credential would couple two independent controls and weaken incident containment.

## Central MSA ownership

`ContextualWisdomLab/.github` owns the scheduler, dispatch authorization, model-provider configuration, credential binding, and fail-closed repair contract. Leaf repositories receive the behavior through the central reusable workflow and do not copy provider credentials or scheduler implementation.

The central scheduler established by the baseline repair runs once per hour, dispatches at most one repair per invocation, and binds privileged implementation to the immutable called-workflow source. The NVIDIA migration changes only the model transport used by the write-capable autofix worker.

## Provider contract

The pinned OpenCode runtime is configured with one enabled provider, `nvidia-nim`, using the OpenAI-compatible adapter and the NVIDIA hosted endpoint:

```text
https://integrate.api.nvidia.com/v1
```

The primary repair model is `mistralai/mistral-nemotron`; the small model used for bounded helper work is `nvidia/nemotron-3-nano-30b-a3b`. NVIDIA documents both model identifiers and the OpenAI-compatible `/v1/chat/completions` endpoint. Mistral-Nemotron is selected for agentic coding and tool-calling capability; Nemotron 3 Nano is selected as a lower-active-parameter helper model rather than as a fallback provider.

Only the `nvidia-nim` provider is enabled. GitHub Models configuration, model identifiers, base URLs, and model-auth fallbacks are absent from the scheduled autofix execution path.

## Credential boundary

The organization secret is bound as:

```yaml
NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
```

It is present only on the two steps that execute OpenCode: ordinary review-feedback repair and merge-conflict repair. Earlier metadata collection, checkout, context preparation, validation, commit, and push steps do not receive the NVIDIA credential.

The workflow passes the key through an environment variable and OpenCode substitutes `{env:NVIDIA_API_KEY}` into the provider configuration. The key is never written to repository files, command arguments, generated prompts, or logs. A missing secret is a fatal configuration error; the workflow does not fall back to `GITHUB_TOKEN`, the GitHub Models token, or another provider.

GitHub notes that a missing secret expression resolves to an empty string and recommends environment-variable delivery rather than command-line delivery. The explicit preflight therefore prevents an ambiguous unauthenticated provider request and preserves fail-closed behavior.

## Repair sandbox and write boundary

The model transport change does not expand agent permissions. OpenCode continues to deny shell, task, web-fetch, web-search, language-server, and external-directory access. It may read, search, list, and edit only the validated same-repository pull-request worktree and only paths authorized by current actionable review context. The workflow validates the live base/head metadata before execution, validates changed files afterward, and refuses to push if the head moved.

GitHub repository credentials and the NVIDIA model credential remain separate. The existing short-lived GitHub App/OIDC exchange and branch-write token chain are not used for model authentication. Conversely, `NVIDIA_NIM_API_KEY` is not used for GitHub reads or writes.

## Verification contract

Automated tests must prove all of the following:

1. The repair scheduler retains the approved hourly cron expression.
2. The OpenCode configuration enables only `nvidia-nim`.
3. Primary and small model identifiers match NVIDIA's published identifiers.
4. The provider uses the OpenAI-compatible package, NVIDIA base URL, and environment substitution.
5. Exactly two OpenCode execution steps receive `NVIDIA_API_KEY` from `secrets.NVIDIA_NIM_API_KEY`.
6. GitHub Models credentials, providers, model identifiers, base URLs, and `USE_GITHUB_TOKEN` model-auth fallback are absent from the autofix workflow.
7. The read-only review workflow is unchanged by this migration.
8. The exact current head passes the repository's complete test, statement/branch coverage, docstring, workflow, security, OpenCode, Noema, and branch-protection gates.

## Rollback

Rollback is a normal revert of the NVIDIA transport commit. A rollback must not reintroduce an implicit GitHub-token model-auth fallback or modify the independent review-agent credential system. If NVIDIA NIM is unavailable, scheduled autofix must fail closed while review, checks, and manual maintenance remain available.

## References

GitHub, Inc. (n.d.). *Secrets reference*. GitHub Docs. Retrieved August 4, 2026, from https://docs.github.com/en/actions/reference/security/secrets

NVIDIA Corporation. (n.d.-a). *LLM APIs*. NVIDIA API Catalog. Retrieved August 4, 2026, from https://docs.api.nvidia.com/nim/reference/llm-apis

NVIDIA Corporation. (n.d.-b). *Mistralai / mistral-nemotron*. NVIDIA API Catalog. Retrieved August 4, 2026, from https://docs.api.nvidia.com/nim/reference/mistralai-mistral-nemotron

NVIDIA Corporation. (n.d.-c). *NVIDIA / nemotron-3-nano-30b-a3b*. NVIDIA API Catalog. Retrieved August 4, 2026, from https://docs.api.nvidia.com/nim/re/reference/nvidia-nemotron-3-nano-30b-a3b

OpenCode. (2026, July 28). *Providers*. https://opencode.ai/docs/providers
