# Doctoring record: removing the dormant `nvidia-nim` provider block from `opencode.jsonc`

- **Date:** 2026-08-31
- **Subject:** Two independent investigation passes traced every remaining candidate direct-NVIDIA-NIM
  communication path in this repository, following up on `#1442`'s removal of the dead
  `scripts/ci/select_nvidia_nim_model.py` resolver and `docs/product-technical-gap-baseline.md`'s
  2026-08-30 "ZDR/NIM-routing architecture review" entry (which investigated the same question and
  chose to leave `opencode.jsonc`'s `nvidia-nim` block in place). This pass reaches a different,
  narrower conclusion for that one block: it is fully dead for every automated/CI review path, was
  never live for the reason previously assumed (a `NVIDIA_API_KEY`/`NVIDIA_NIM_API_KEY` naming
  mismatch), and — more importantly — was pinned by two contract-test assertions in
  `scripts/ci/test_strix_quick_gate.sh` that asserted its *presence* as if it were required, which is
  itself misleading and worth fixing per this repo's contract-test discipline.
- **Related:** `#1442` (prior direct-NIM dead-code removal, same rigor: verify zero callers, doctoring
  record, dated gap-baseline entry), `docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`
  (the governing decision: gateway-only routing, fail-closed on gateway unavailability, no
  direct-provider fallback), `docs/product-technical-gap-baseline.md`'s 2026-08-30 "ZDR/NIM-routing
  architecture review" entry (superseded by this record for the `opencode.jsonc` block specifically;
  left unedited per this repo's "append, don't rewrite history" convention — see the dated follow-up
  entry added alongside this record).

## What changed

- Removed the `"nvidia-nim"` provider block from `opencode.jsonc` (previously lines 289-378: the
  `baseURL`/`apiKey` options plus its ten-model catalog). `enabled_providers` (line 9) already listed
  only `"contextual-orchestrator"`, so removing the block changes no runtime selection — it deletes
  dead configuration, not live behavior.
- Fixed `scripts/ci/test_strix_quick_gate.sh`'s two orphaned assertions (previously lines 1481-1482,
  missing the leading tab every neighboring assertion in the same function has — a sign they were
  pasted in out of band) that asserted `opencode.jsonc` *contains* `"nvidia-nim"` and
  `integrate.api.nvidia.com`. These were accurate when authored in commit `c61cb608` (`#1084`,
  2026-08-22, when `nvidia-nim` really was enabled), but `#1364` (`f8823a54`, 2026-08-27) flipped
  `enabled_providers` to gateway-only and rewrote the surrounding workflow-file assertions to forbid
  `nvidia-nim/*` without updating these two lines, leaving them pinning removed behavior as if it were
  still required. Changed both to `assert_file_not_contains`, matching the two `assert_file_not_contains`
  assertions immediately above them in the same function that already forbid the old NVIDIA NIM
  model-id defaults.
- Deleted `docs/nvidia-nim-opencode-hotfix.md` per its own "Rollback" section ("drop the `nvidia-nim`
  provider block ... and delete this note once GitHub Models / OpenCode catalog reliability is
  restored"). Its `OPENCODE_MODEL_CANDIDATES` NIM-prefix rollback step and its
  `NVIDIA_API_KEY: ${{ secrets.NVIDIA_API_KEY }}` workflow binding were already reverted by `#1364`;
  this change completes the third and last rollback step the doc itself specified. Its only other
  in-repo reference was the descriptive mention in `docs/product-technical-gap-baseline.md`'s
  2026-08-30 entry, which is left as-is per the append-only convention.

## Why this is safe

**Zero live callers, confirmed independently by two investigation passes:**

1. `enabled_providers` (`opencode.jsonc:9`) already excluded `nvidia-nim` — OpenCode cannot select an
   unenabled provider regardless of the removed block's content.
2. The dispatch and autofix workflows (`opencode-review-dispatch.yml`, `pr-review-autofix.yml`) build
   their OpenCode config from scratch (`jq -n '{"provider": {}}'` plus a patched-in
   `contextual-orchestrator` block only) — the root `opencode.jsonc`'s provider blocks were never
   copied into the config either workflow actually runs OpenCode against.
3. `OPENCODE_MODEL_CANDIDATES` is set to the single literal value
   `"contextual-orchestrator/orchestrator/free"` (`opencode-review-dispatch.yml`) — no `nvidia-nim/*`
   candidates are ever dispatched.
4. The model-pool step's `env:` block does not forward `NVIDIA_NIM_API_KEY` at all (it is scoped only
   to the earlier sidecar-provisioning step), so even the theoretical `{env:NVIDIA_API_KEY}` alias in
   the removed block would have resolved empty in every workflow run today.

Grepping the repository after this change for `nvidia-nim` and `NVIDIA_API_KEY` returns:
`scripts/ci/run_opencode_review_model_pool.sh` (dead candidate-handling branches, `is_nvidia_nim_candidate`/
`is_schema_repair_candidate`/the credential bridge/`should_skip_model_candidate`/`cap_model_run_timeout`
— never exercised because no `nvidia-nim/*` candidate is ever dispatched per point 3 above; left
untouched in this change, split into its own follow-up per this org's stated preference for splitting
unrelated dead-code cleanups — see `#1437`'s review thread precedent), `scripts/ci/test_strix_quick_gate.sh`
(its own workflow-file assertions forbidding `nvidia-nim/`, unrelated `nvidia_nim`-with-underscore
fixture values inside Strix's own quick-gate self-test harness, and the two now-corrected assertions
above), and `.github/workflows/hourly-nvidia-nim-review-repair.yml` plus its per-product hourly-caller
tests (named after the scheduler's NIM heritage but gateway-only per ADR-0003/CLAUDE.md — unrelated to
`opencode.jsonc`'s provider block). No executable reference to the removed block remains.

**A second, separate audit traced the other candidate direct-NIM surfaces flagged for this pass and
found no live communication to remove:**

- `scripts/ci/strix_quick_gate.sh`'s `is_known_foreign_provider_api_base()` (single caller inside
  `resolved_llm_api_base_for_model()`) is a leak-*blocker* — matching it clears a resolved API base
  rather than granting one, specifically to stop a leaked NVIDIA NIM/GitHub Models/OpenRouter base URL
  from being reused when Strix falls back to an explicit direct-OpenAI model. It is also unreachable
  in the wired `strix.yml` today, since that workflow hardcodes `STRIX_LLM_FILE` to the literal
  `orchestrator/free` and forces `STRIX_FALLBACK_MODELS: ""`. Left untouched: it is a correctness
  guard with its own dedicated regression test
  (`tests/test_strix_openai_fallback_api_base.py`), not a bypass.
- All four workflows that provision `NVIDIA_NIM_API_KEY` (`noema-review.yml`, `opencode-review-dispatch.yml`,
  `pr-review-autofix.yml`, `strix.yml`) do so only as an `env:` input to the
  "Provision contextual-orchestrator ... sidecar" step, which registers the secret into the vendored
  gateway process's own KV (`register_review_credentials`) — never into a direct `curl`. None of the
  four workflow files reference `integrate.api.nvidia.com`.
- `scripts/ci/zdr_policy.py`'s `PROVIDER_BASE_URLS["nvidia_nim"]` fallback is consumed only inside the
  vendored `contextual-orchestrator` sidecar process itself (`contextual_orchestrator_review_launcher.py`,
  `contextual_orchestrator_review_policy.py`), building the gateway's own internal routing table for
  models it discovered via the KV credential it registered. This is the intended architecture — "the
  writer runs `contextual-orchestrator/orchestrator/free`" per `AGENTS.md` — not a bypass of it.
- The 2026-08-30 ADR-0003 amendment already confirms `strix.yml` forces `orchestrator/free` with zero
  fallback candidates and fails closed unless the sidecar reports the exact expected loopback base URL;
  no remaining Strix code path can select `nvidia_nim/*` directly. Left untouched.

## Audit trail

- `#1442`'s doctoring record and `docs/product-technical-gap-baseline.md`'s 2026-08-30 entry — the
  prior investigation this pass follows up on and narrows.
- This PR's own two investigation passes (`opencode-config`, `strix-noema-allowlist`) — full
  file/line traces underlying the summary above.
- This PR's diff — the removal and contract-test fix themselves.
