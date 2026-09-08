# NVIDIA NIM OpenCode hotfix retirement

## Decision

The legacy direct-provider OpenCode hotfix is retired. Protected `main` now enables only the `contextual-orchestrator` provider in `opencode.jsonc`, with both normal and small-model review requests routed through `contextual-orchestrator/orchestrator/free`. Direct NVIDIA NIM provider selection is therefore not part of the OpenCode review contract.

The removed `docs/nvidia-nim-opencode-hotfix.md` described a superseded architecture: direct `nvidia-nim` provider configuration, `NVIDIA_API_KEY` binding, and an administrator-bypass hotfix window. Keeping that document beside the current gateway-only configuration created an operational contradiction and could mislead a maintainer into restoring a retired direct-provider path.

## Current authority boundary

- `ContextualWisdomLab/.github` owns the review workflows and gateway integration.
- `opencode.jsonc` enables only `contextual-orchestrator` and denies direct-provider fallback.
- NVIDIA NIM credentials may be registered into contextual-orchestrator's provider-discovery boundary; they are not an OpenCode provider credential or a direct workflow model binding.
- The write-capable scheduled autofix path follows the same gateway-only boundary documented in `docs/doctoring/hourly-nvidia-nim-autofix.md` and ADR-0003.
- Queue-saturation administrator bypass, when separately proven under the current control-plane contract, is an admission-recovery mechanism and must not be documented as a provider-specific hotfix permission.

## Verification

This record was created from protected `main@81b6f20d7f701bd2e50642ab107ab0f187ae6dc9`. At that revision, `opencode.jsonc` declares `enabled_providers: ["contextual-orchestrator"]`, uses `contextual-orchestrator/orchestrator/free`, and contains no live `nvidia-nim` provider block. The existing `docs/doctoring/hourly-nvidia-nim-autofix.md` already records the corrected gateway-only provider contract.

No runtime source, credential, model-selection rule, security threshold, branch-protection rule, or review authority is changed by this documentation cleanup.