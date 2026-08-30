# Doctoring record: removing leftover direct NVIDIA NIM communication

- **Date:** 2026-08-30
- **Subject:** the 2026-08-30 owner directive's same-date follow-up instruction adds "NIM 직접 통신은
  제거 대상" (direct NIM communication is a removal target) to the standing autonomous loop. This
  record covers what was found, what was removed now, and what is flagged for a dedicated follow-up
  rather than rushed in the same pass.
- **Related:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](../adr/0003-contextual-orchestrator-vendored-free-zdr.md),
  [`docs/doctoring/noema-orchestrator-free-zdr.md`](noema-orchestrator-free-zdr.md)

## Scope of the search

Searched all three attached repos (`.github`, `noema`, `contextual-orchestrator`) for
`integrate.api.nvidia.com` / `NVIDIA_NIM_API_KEY` references, then filtered out the large majority
that are legitimate: the five-provider-secret KV bootstrap pattern (`NVIDIA_NIM_API_KEY` flowing into
`contextual-orchestrator`'s KV, never read directly by review/runtime code), `scripts/ci/zdr_policy.py`'s
provider base-URL table (the gateway's own routing table — it has to know the real upstream endpoint
to proxy to it, which is not the same as a caller bypassing the gateway), and the many
`*_hourly_review_caller.py` contract tests asserting the gateway-only pattern is followed. `noema`'s
actual runtime (`src/`) has zero NVIDIA references at all — it is a pure OIDC token broker and never
touches the review/LLM path directly.

## Removed: `scripts/ci/select_nvidia_nim_model.py`

A real, direct-HTTPS-to-`integrate.api.nvidia.com` script (`GET /v1/models` with a bearer token, no
gateway involved) that resolved which NVIDIA NIM model id was live for "the scheduled autofix worker"
per its own docstring. `grep -r select_nvidia_nim_model` across the whole repository (including every
`.github/workflows/*.yml`) found zero callers beyond its own now-removed test — the workflow that used
to invoke it was already migrated to `contextual-orchestrator`'s own auto-discovery
(`discover_all_models()` / the review policy catalog), leaving this script and
`tests/test_select_nvidia_nim_model.py` as orphaned direct-provider code with no remaining purpose.
Removed both. Full suite after removal: 1851 passed, 1 skipped (down from 1884 only because the removed
test file's own parametrized cases are gone); coverage and docstring gates for `scripts/ci/` unaffected
(a pre-existing, unrelated `scripts/ci/pingora_edge_policy.py` line-274 gap — confirmed independently by
two other concurrent agents today to reproduce identically on a clean `main` checkout — is not from this
change and is not fixed here).

## Flagged, not removed: `opencode.jsonc`'s `nvidia-nim` / `github-models` provider catalogs

`opencode.jsonc` still carries full `nvidia-nim` (direct `https://integrate.api.nvidia.com/v1`, its own
`NVIDIA_API_KEY` — note: not even the standard `NVIDIA_NIM_API_KEY` name) and `github-models` provider
blocks (~300 of the file's 416 lines), even though the file's own top-of-file comment states "there is
no direct-provider fallback for review content" and `enabled_providers` lists only
`["contextual-orchestrator"]`. This is **not** dead configuration the way the removed script was:
`tests/test_opencode_agent_contract.py` actively pins an `OPENCODE_MODEL_CANDIDATES` pool in
`.github/workflows/opencode-review-dispatch.yml` built from exactly these `nvidia-nim/*` and
`github-models/*` entries (~100 lines of contract assertions), and `scripts/ci/run_opencode_review_model_pool.sh`
iterates that candidate pool by invoking OpenCode with an explicit `--model <candidate>` override per
attempt — which is a separate mechanism from `enabled_providers`/the file's default `model` setting, so
it is not obviously blocked by `enabled_providers` the way a first read suggests.

Whether this dispatch-level fallback pool should also be migrated to route exclusively through
`contextual-orchestrator` (eliminating the last vestige of direct-provider communication in the review
pipeline, consistent with today's instruction) or is a deliberately preserved resilience tier distinct
from the gateway's own free-first/priced-fallback behavior is a real architecture question, not a
copy-paste dead-code removal: ripping out ~300 lines of actively-tested provider configuration and the
dispatch workflow's candidate-pool mechanism in the same pass as an unrelated Strix/NIM cleanup risks a
shallow, wrong change to the org's actual required review pipeline. Tracked as the next concrete item in
`docs/product-technical-gap-baseline.md` for a dedicated follow-up PR, not implemented here.

## Audit trail

- `scripts/ci/select_nvidia_nim_model.py`, `tests/test_select_nvidia_nim_model.py` — removed.
- `opencode.jsonc` (`provider.nvidia-nim`, `provider.github-models`), `.github/workflows/opencode-review-dispatch.yml`
  (`OPENCODE_MODEL_CANDIDATES`), `scripts/ci/run_opencode_review_model_pool.sh`,
  `tests/test_opencode_agent_contract.py` — read and flagged, not modified.
- `docs/product-technical-gap-baseline.md` — follow-up item recorded.
