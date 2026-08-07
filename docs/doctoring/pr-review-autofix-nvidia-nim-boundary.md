# OpenCode PR autofix NVIDIA NIM boundary

## Status

This doctoring record describes the provider and credential boundary for the write-capable `PR Review Autofix` control-plane worker. It does **not** change the read-only OpenCode review agent credential chain, reviewer identity, approval policy, branch protection, or merge policy.

## Problem

The central autofix worker previously configured OpenCode inference through GitHub Models and `STRIX_GITHUB_MODELS_TOKEN`. That coupling conflicts with the control-plane requirement that GitHub Actions repair agents use OpenCode with the organization `NVIDIA_NIM_API_KEY`, while repository-write credentials remain separately scoped to GitHub operations.

For a write-capable worker, mixing model-provider and repository credentials also increases the number of credential paths that must be reasoned about during incident response and acquisition diligence. The safer boundary is one explicit model secret, one explicit provider, and an unchanged GitHub write-identity chain.

## Decision

`pr-review-autofix.yml` now applies the following contract to both ordinary review-feedback autofix and merge-conflict resolution:

1. OpenCode enables only the `nvidia-nim` provider for model inference.
2. The selected model is `nvidia/llama-3.3-nemotron-super-49b-v1.5`; the small model is `meta/llama-3.3-70b-instruct`.
3. The workflow maps the organization Actions secret `NVIDIA_NIM_API_KEY` into the process-local `NVIDIA_API_KEY` expected by the OpenCode provider configuration.
4. The provider uses the OpenAI-compatible NVIDIA endpoint `https://integrate.api.nvidia.com/v1`.
5. The worker fails closed before invoking OpenCode when `NVIDIA_API_KEY` is absent.
6. `USE_GITHUB_TOKEN` is disabled for OpenCode model-provider discovery so GitHub Models is not a hidden inference fallback.
7. Existing `PR_REVIEW_MERGE_TOKEN` → `OPENCODE_APPROVE_TOKEN` → OpenCode app-token → `github.token` repository-write selection remains unchanged in the GitHub-facing steps.
8. OpenCode keeps shell execution denied and may edit only the exact allowlisted paths derived from current review feedback.

## Security and privacy rationale

NVIDIA NIM exposes OpenAI-compatible inference APIs, allowing the existing OpenCode OpenAI-compatible provider adapter to be used without introducing a provider-specific execution surface. OpenCode documents NVIDIA as a supported provider, supports `NVIDIA_API_KEY` for headless environments, and allows a custom base URL for NIM deployments. GitHub documents that Actions secrets can be injected through the `secrets` context and recommends environment variables rather than command-line arguments for sensitive values.

The workflow therefore keeps the model credential in a step-scoped environment variable rather than embedding it in configuration, arguments, logs, repository content, review text, or generated artifacts. A missing secret is an error rather than a reason to fall back to GitHub Models, a public/free pool, or another provider.

## Test-first evidence

The permanent regression contract is `tests/test_pr_review_autofix_nvidia_nim_contract.py`. It requires:

- the exact NIM primary and small model bindings;
- `enabled_providers` containing only `nvidia-nim`;
- the NVIDIA OpenAI-compatible base URL and environment-backed API key;
- the `NVIDIA_NIM_API_KEY` Actions secret mapping;
- absence of `STRIX_GITHUB_MODELS_TOKEN`, `github-models`, and `models.github.ai` from the autofix workflow; and
- preservation of the existing GitHub repository-write credential chain.

The RED test was committed before the workflow change. The subsequent production commit changed only `.github/workflows/pr-review-autofix.yml`; its diff removed the GitHub Models provider and added the fail-closed NVIDIA NIM path for both write-capable OpenCode invocations.

## Operational acceptance

This boundary is not merge evidence by itself. The containing pull request remains subject to current-head CI, security, coverage, docstring, packaging, provenance, independent review, branch-protection, and repository-policy gates. Pending, queued, cancelled, predecessor-head, or synthetic-merge evidence is not success.

The organization secret must be exposed only to repositories that are authorized to execute the central worker. Secret availability should be reviewed through GitHub organization Actions-secret access policy. The secret value must never be copied into PR comments, logs, artifacts, prompts, generated patches, or shareable review evidence.

## Rollback

Rollback is appropriate only if NVIDIA NIM is intentionally removed as the approved Actions repair provider. A rollback must update the permanent test, this doctoring record, and the workflow in one reviewed change and must not silently reintroduce GitHub Models or another provider as a fallback. Repository-write identity selection must remain separate from model-provider credentials.

## References

GitHub, Inc. (2026). *Using secrets in GitHub Actions*. GitHub Docs. https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

NVIDIA Corporation. (2026). *Architecture—NVIDIA NIM for Large Language Models*. NVIDIA Docs. https://docs.nvidia.com/nim/large-language-models/latest/reference/architecture.html

NVIDIA Corporation. (2026). *Quickstart—NVIDIA NIM for Large Language Models*. NVIDIA Docs. https://docs.nvidia.com/nim/large-language-models/latest/get-started/quickstart.html

OpenCode. (2026). *Providers*. https://opencode.ai/docs/providers
