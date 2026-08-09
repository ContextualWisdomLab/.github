# NVIDIA NIM OpenCode model priority (hotfix)

Status: historical rollout note. Current secret and governance contracts are
normative in `docs/automation/SECURITY.md`; administrative bypass is not an
accepted activation or rollback path.

## Why

OpenCode Agent failed to produce a usable review on the PR thread starting at
ContextualWisdomLab/fast-mlsirm#290 (`opencode-review` check **skipped**, no
`opencode-agent[bot]` review comment). Central review therefore prioritizes
**NVIDIA NIM** models as additional catalog candidates so the model pool can
still emit APPROVE / REQUEST_CHANGES when GitHub Models / free tiers stall.

## Changes

1. `opencode.jsonc`
   - `enabled_providers`: `nvidia-nim` first, then `github-models`
   - default `model` / `small_model` prefer NIM Nemotron / Llama 3.3
   - new OpenAI-compatible provider `nvidia-nim` → `https://integrate.api.nvidia.com/v1`
     with process-local `apiKey: {env:NVIDIA_API_KEY}`, sourced only from the
     scoped organization secret `NVIDIA_NIM_API_KEY`
2. `.github/workflows/opencode-review-dispatch.yml`
   - `OPENCODE_MODEL_CANDIDATES` prefixes six NIM models before existing pool
   - binds process-local `NVIDIA_API_KEY` from `${{ secrets.NVIDIA_NIM_API_KEY }}`
3. `scripts/ci/run_opencode_review_model_pool.sh`
   - skips `nvidia-nim/*` when scoped `NVIDIA_NIM_API_KEY` is unset

## Historical activation constraint

- Branch protection and rulesets are not bypassed to activate a model-provider
  change; eligible review and protected-main consumer evidence remain required.
- **Do not** permanently weaken Security Scan, trivy-fs, osv-scan, or
  CodeQL gates.
- **Do not** flip OpenCode agent `permission.edit` / `bash` from `deny` to
  `allow` permanently; review agents remain read-only.
- Org secret `NVIDIA_NIM_API_KEY` must be set on ContextualWisdomLab for NIM
  pool entries to execute; without it the pool falls through to prior candidates.

## Rollback

Remove the `nvidia-nim/*` prefixes from `OPENCODE_MODEL_CANDIDATES`, drop the
`nvidia-nim` provider block, and delete this note once GitHub Models / OpenCode
catalog reliability is restored.

## Secret name

Org secret is **`NVIDIA_NIM_API_KEY`**. Workflows bind it to process env
`NVIDIA_API_KEY`; there is no fallback to a legacy `secrets.NVIDIA_API_KEY`, so
`opencode.jsonc` `{env:NVIDIA_API_KEY}` resolves only from the scoped secret.

## Large-repo OpenCode timeouts (~1 hour)

Primary/default run timeouts and the dynamic queue timeout cap default to
**3600s** (hour-class) so large repositories are not cut off by the old 600s
default when env is unset. Free-tier failover remains capped at 600s.
Workflow-provided values (e.g. 5400s) still win over defaults.
