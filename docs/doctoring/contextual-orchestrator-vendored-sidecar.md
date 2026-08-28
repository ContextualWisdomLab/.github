# Doctoring record: contextual-orchestrator vendored review sidecar (ZDR-first `orchestrator/free`)

- **Date:** 2026-08-27
- **Subject:** Central CI review no longer pins direct provider endpoints; it
  routes through a vendored `contextual-orchestrator` gateway sidecar under the
  fail-closed zero-cost pool `orchestrator/free`, with ZDR-compliant routes
  prioritized.
- **Decision record:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](adr/0003-contextual-orchestrator-vendored-free-zdr.md)

## What changed

`pr-review-autofix.yml` now provisions the sidecar
(`scripts/ci/contextual_orchestrator_review_sidecar.sh`) before its OpenCode
runs, seeds the five provider secrets (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
`NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) into the
process-local KV, runs auto model discovery over them, and serves the
ZDR-prioritized free catalog at loopback. Both the ordinary autofix and the
conflict-repair agent run `--model contextual-orchestrator/orchestrator/free`.
The shared `opencode.jsonc` default route changes identically.

`noema-review.yml` provisions the same sidecar with the same five secrets and
points the required Noema LLM step at the loopback `orchestrator/free` pool.
The public-repo NVIDIA NIM hardcode is deleted. `call_llm` keeps SSRF closed
for arbitrary private IPs and `localhost`, and allows only the sidecar
loopback (`127.0.0.1` / `::1`) when it matches the exact configured sidecar
base URL. The via-orchestrator marker is metadata only and never widens this
allowlist.

`NVIDIA_NIM_API_KEY_SUB` and `BYTEZ_API_KEY` have no other workflow reference in
this repository; the gateway KV is their only consumer, matching the
orchestrator's `review_gateway.REVIEW_CREDENTIAL_NAMES`.

## Why this is still the same trust boundary

- The OpenCode subprocess still runs with `GITHUB_TOKEN` / `GH_TOKEN` /
  `ACTIONS_ID_TOKEN_REQUEST_*` stripped (the exact-credential sanitization is
  unchanged and asserted by contract tests).
- Mutation still requires `PR_REVIEW_MERGE_TOKEN` /
  `OPENCODE_APPROVE_TOKEN` / the exchanged OpenCode app token; `github.token`
  remains read-only.
- The gateway binds to loopback only; it never leaves the runner. Secrets are
  bootstrap transport into the KV and are never read back from environment at
  request time.
- Noema reviewer identity is unchanged: `NOEMA_REVIEW_TOKEN` / GitHub App /
  OIDC. Review mutation is still not `github.token`.

## ZDR definition and evidence

ZDR here follows OpenRouter's definition — "a provider will not store your
data for any period of time", and zero retention implies no training. The
policy is conservative: an un-ascertained provider is treated as retaining and
training (OpenRouter's own stance). Evidence sources:

1. OpenRouter ZDR endpoint feed `https://openrouter.ai/api/v1/endpoints/zdr`
   (auto-updated, machine-readable) — authoritative when egress allows it;
2. the dated static attestation table in `scripts/ci/zdr_policy.py`
   (OpenRouter scope attested; NVIDIA NIM primary/sub, OpenAI, and Bytez
   direct scopes are not attested as zero-retention and are therefore
   non-ZDR by default).

## Audit trail

- `scripts/ci/zdr_policy.py` — org ZDR provider policy (offline-tested).
- `scripts/ci/contextual_orchestrator_review_policy.py` — discovery report →
  ZDR-prioritized free agents catalog + audit report (offline-tested).
- `scripts/ci/contextual_orchestrator_review_launcher.py` — same-process KV
  registration + discovery + serve (runs in the vendored runtime only).
- `scripts/ci/contextual_orchestrator_review_sidecar.sh` — pinned-SHA vendoring +
  health gate + GITHUB_ENV export.
- `tests/test_zdr_policy.py`,
  `tests/test_contextual_orchestrator_review_policy.py`,
  `tests/test_contextual_orchestrator_review_sidecar_contract.py`,
  `tests/test_pr_review_autofix_nvidia_nim_contract.py`,
  `tests/test_pr_review_autofix_writer_security_contract.py`,
  `tests/test_noema_review_gate.py`,
  `docs/doctoring/noema-orchestrator-free-zdr.md`.

## 2026-08-28 runtime correction

The first post-merge Strix execution (`33139957477`) failed before serving: the
pinned orchestrator's `load_agents()` indexes the top-level `agents` field, but
the launcher persisted only the list value. Follow-up PR [#1370](https://github.com/ContextualWisdomLab/.github/pull/1370)
wraps both the launcher output and the standalone policy builder output in the
loader-compatible `{"agents": [...]}` envelope. The regression is covered by
`tests/test_contextual_orchestrator_review_policy.py` and the sidecar contract;
the full local suite passed with `1689 passed, 1 skipped, 16 subtests passed`.

The PR-target Noema check still runs the trusted base copy until this trusted
workflow change is merged, so its reproduction of the old error is retained as
bootstrap evidence rather than treated as a current-head runtime result.

## 2026-08-28 post-#1370 runtime correction

Main push run `33141468804` confirmed that the catalog envelope correction
reached the Strix sidecar, but LiteLLM rejected the child model
`orchestrator/free` because it had no provider prefix. Follow-up commits
`9f58d74` and `5aa0a20` map only the pinned gateway request to
`openai/orchestrator/free`, fail closed when that gateway base is absent or
not loopback, and keep the loopback sidecar receiving `orchestrator/free`.

The same follow-up masks the dynamic sidecar bearer before writing `GITHUB_ENV`
and rejects carriage returns/newlines in an override. This closes the runtime
log exposure observed in the Noema step environment block. Focused contracts
pass (`32 passed`) and the full local suite passes (`1689 passed, 1 skipped`).
The main Strix rerun and an independently authorized Noema model verdict are
still required before claiming end-to-end review completion.
