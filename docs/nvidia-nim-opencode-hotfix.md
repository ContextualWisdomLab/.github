# NVIDIA NIM OpenCode model priority (hotfix)

## Why

OpenCode Agent failed to produce a usable review on the PR thread starting at
ContextualWisdomLab/fast-mlsirm#290 (`opencode-review` check **skipped**, no
`opencode-agent[bot]` review comment). Central review therefore prioritizes
**NVIDIA NIM** models as additional catalog candidates so the model pool can
still emit APPROVE / REQUEST_CHANGES when a hosted NIM session can complete.

## Changes

1. `opencode.jsonc`
   - `enabled_providers`: `nvidia-nim` only
   - default `model` / `small_model` are NIM Nemotron / Llama 3.3
   - OpenAI-compatible provider `nvidia-nim` → `https://integrate.api.nvidia.com/v1`
     with `apiKey: {env:NVIDIA_API_KEY}`
   - no `github-models` provider and no `STRIX_GITHUB_MODELS_TOKEN`
2. `.github/workflows/opencode-review-dispatch.yml`
   - `OPENCODE_MODEL_CANDIDATES` is NIM-first; GitHub Models and Terra are omitted
   - binds `NVIDIA_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}`
   - if `NVIDIA_NIM_API_KEY` is unset the pool fails closed
3. `scripts/ci/run_opencode_review_model_pool.sh`
   - if NIM candidates are configured and `NVIDIA_NIM_API_KEY` is unset, fail
     closed instead of falling through to GitHub Models

## Temporary permission bypass (hotfix only)

For this merge-aid hotfix only:

- Branch-protection / ruleset admin override may be used to land the central
  `.github` change if required checks conflict during the hotfix window.
- **Do not** permanently weaken Security Scan, trivy-fs, osv-scan, or
  CodeQL gates.
- **Do not** flip OpenCode agent `permission.edit` / `bash` from `deny` to
  `allow` permanently; review agents remain read-only.
- Org secret `NVIDIA_NIM_API_KEY` must be set on ContextualWisdomLab for NIM
  review-pool entries to execute; without it the OpenCode pool fails closed.

## Rollback

Remove the `nvidia-nim/*` prefixes from `OPENCODE_MODEL_CANDIDATES` only if a
later policy names a different required review provider. Do not restore GitHub
Models to the OpenCode review catalog. Delete this note once the NIM-only
review catalog is the standing contract.

## Secret name

Org secret is **`NVIDIA_NIM_API_KEY`**. Workflows bind it to process env `NVIDIA_API_KEY`
with no `secrets.NVIDIA_API_KEY` fallback so `opencode.jsonc` `{env:NVIDIA_API_KEY}` resolves.

## Large-repo OpenCode timeouts (NIM ≥7200s)

The 180s NIM per-candidate timeout killed NVIDIA sessions in three minutes
and skipped the review (ContextualWisdomLab/fast-mlsirm#290). Central
dispatch now sets:

- `OPENCODE_NVIDIA_NIM_RUN_TIMEOUT_SECONDS` and
  `OPENCODE_NVIDIA_NIM_TOTAL_BUDGET_SECONDS` to **7200** (one two-hour NIM
  attempt, then skip remaining NIM so seven 7200s candidates cannot stack)
- generic / cadence / dynamic-cap / central-fallback run timeouts to **7200**
- free-tier at **3600s** (unchanged short cap; no GitHub Models GPT-5 path)

GitHub Models is removed from the OpenCode review catalog. If
`NVIDIA_NIM_API_KEY` is unset, OpenCode fails closed (skip /
REQUEST_CHANGES / status) instead of falling through to GitHub Models or
Luna. Strix remains a separately governed protected-main contract and keeps
its authenticated multi-provider fail-closed fallback policy. Concurrency
stays PR-number scoped with `cancel-in-progress: true`; pool max cycles and
attempts stay at 1 so the dispatch queue does not multiply unbounded parallel
two-hour jobs.

## Next provider: contextual-orchestrator

NIM-direct is the current default. The long-term OpenCode provider is
ContextualWisdomLab/contextual-orchestrator. Dispatch may attach one
optional provider block when `CONTEXTUAL_ORCHESTRATOR_URL` is set; it
does not start the sidecar and never falls back to GitHub Models. See
[`docs/doctoring/opencode-contextual-orchestrator-sidecar.md`](doctoring/opencode-contextual-orchestrator-sidecar.md).
