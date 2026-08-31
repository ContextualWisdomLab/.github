# NVIDIA NIM OpenCode model priority (hotfix) — ROLLED BACK, HISTORICAL

**Status (2026-08-31): this hotfix is no longer active.** The six-model NIM
prefix this note describes was removed from
`.github/workflows/opencode-review-dispatch.yml`'s `OPENCODE_MODEL_CANDIDATES`
by `f8823a54` (#1364, "route Noema review through vendored
contextual-orchestrator"); that variable has held the single value
`"contextual-orchestrator/orchestrator/free"` (contract-pinned by
`tests/test_opencode_agent_contract.py`) ever since, and `opencode.jsonc`'s
embedded config for the CI dispatch path likewise renders
`enabled_providers: ["contextual-orchestrator"]` with no NIM entry. Per this
note's own "Rollback" section below, it should have been deleted once
catalog reliability was restored; it was not, and stayed factually stale for
over a month (last touched at `c7a4bad6`, #682, 2026-07-31) before this
correction. Left in place as a historical record rather than deleted, per
this repo's "append a dated note, don't rewrite history" documentation
convention (see `docs/doctoring/direct-nvidia-nim-communication-removal.md`
for the sibling record of the *code* that implemented an unrelated,
already-dead direct-NIM resolver). The `nvidia-nim` provider block still
declared in root `opencode.jsonc` (unused by the CI dispatch path, which
generates its own provider list) is a deliberate, still-tested fallback
capability for `scripts/ci/run_opencode_review_model_pool.sh`
(`is_nvidia_nim_candidate`, exercised by `tests/test_opencode_model_pool_runner.py`),
not orphaned code — removing it is a separate resilience-tradeoff decision,
not a documentation fix, and is out of scope here. See
`docs/product-technical-gap-baseline.md`'s "Direct-NIM-communication audit"
entry (2026-08-31) for the full investigation this correction closes out.

## Why (historical — describes the hotfix as it was, not current state)

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
     with `apiKey: {env:NVIDIA_API_KEY}`
2. `.github/workflows/opencode-review-dispatch.yml`
   - `OPENCODE_MODEL_CANDIDATES` prefixes six NIM models before existing pool
   - binds `NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}`
3. `scripts/ci/run_opencode_review_model_pool.sh`
   - skips `nvidia-nim/*` when `NVIDIA_API_KEY` is unset (same pattern as OpenRouter)

## Temporary permission bypass (hotfix only)

For this merge-aid hotfix only:

- Branch-protection / ruleset admin override may be used to land the central
  `.github` change if required checks conflict during the hotfix window.
- **Do not** permanently weaken Security Scan, trivy-fs, osv-scan, or
  CodeQL gates.
- **Do not** flip OpenCode agent `permission.edit` / `bash` from `deny` to
  `allow` permanently; review agents remain read-only.
- Org secret `NVIDIA_API_KEY` must be set on ContextualWisdomLab for NIM pool
  entries to execute; without it the pool falls through to prior candidates.

## Rollback

Remove the `nvidia-nim/*` prefixes from `OPENCODE_MODEL_CANDIDATES`, drop the
`nvidia-nim` provider block, and delete this note once GitHub Models / OpenCode
catalog reliability is restored.

## Secret name

Org secret is **`NVIDIA_NIM_API_KEY`**. Workflows bind it to process env `NVIDIA_API_KEY`
(fallback: `secrets.NVIDIA_API_KEY` if present) so `opencode.jsonc` `{env:NVIDIA_API_KEY}` resolves.

## Large-repo OpenCode timeouts (~1 hour)

Primary/default run timeouts and the dynamic queue timeout cap default to
**3600s** (hour-class) so large repositories are not cut off by the old 600s
default when env is unset. Free-tier failover remains capped at 600s.
Workflow-provided values (e.g. 5400s) still win over defaults.
