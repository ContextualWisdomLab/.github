# Doctoring record: contextual-orchestrator vendored review sidecar (ZDR-first `orchestrator/free`)

- **Date:** 2026-08-27
- **Subject:** Central CI review no longer pins direct provider endpoints; it
  routes through a vendored `contextual-orchestrator` gateway sidecar under the
  fail-closed zero-cost pool `orchestrator/free`, with ZDR-compliant routes
  prioritized.
- **Decision record:** [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](adr/0003-contextual-orchestrator-vendored-free-zdr.md)

## 2026-08-28 Strix request envelope

The first post-#1373 main Strix execution reached the gateway and selected
`openai/orchestrator/free`, but the pinned server rejected the initial agent
request with HTTP 413 (`request_too_large`). The vendored server's generic
`SecurityConfig.max_body_bytes` default is 64 KiB; Strix and Noema requests
include tool schemas and repository context and therefore need a larger,
still-bounded integration envelope. The review launcher now sets an explicit
8 MiB limit for this sidecar only; the library default remains unchanged for
other deployments. Its pinned-SHA preflight uses the public server builder and
loopback HTTP boundary to verify that an oversized request returns 413; it does
not depend on private server helpers or error-message text. A 413 remains
fail-closed if a request exceeds that bound.
This 8 MiB value is a local ingress safety bound for this review sidecar, not a
general OpenAI multimodal limit. OpenAI's official images guide permits image
URLs, Base64 data URLs, and file IDs in ordinary model-input JSON and specifies
up to 512 MB total payload for an image-input request. The separate Files API
specifies up to 512 MB per uploaded file, while Batch has its own 200 MB JSONL
limit. A URL or file ID keeps the model-input JSON small; an inline Base64 image
can exceed this sidecar's 8 MiB review envelope. The sidecar therefore fails
that local boundary closed and must not claim general 512 MB multimodal
compatibility. Supporting that broader contract requires a separately governed
streaming/spooling path and provider capability checks; adding `/files` alone
would not handle an inline Base64 image in an ordinary JSON request.
The sidecar must measure representative Strix envelopes and keep provider/model
context failures distinct from its own HTTP framing failure.

## 2026-08-29 Noema preflight batching

DiskSage Noema jobs `99111099730` and `99110885279` logged
`request_failed status=413 code=request_too_large` before startup. That line was
the sidecar's intentional oversized `Content-Length` contract test, not model
discovery or a provider response. The actual terminal condition was exhaustion
of the initially selected provider routes before healthz. The contract probe now
captures and asserts its expected diagnostic without emitting it, while runtime
preflight tries a maximum of 24 discovered routes in concurrent batches of four
and stops after the first batch with usable text. Every route still uses the
ten-second timeout, zero retries, the same plain-chat payload, and sanitized
evidence; exhausting the bounded batches remains a startup failure.
Provider discovery must also be complete. If any configured provider reports a
discovery error, the launcher records only sanitized provider and error
identifiers with `complete: false`, omits the partial model list, and stops
before serving traffic. A partial catalog is not availability evidence.
The pin includes upstream `#887` (`2591b66`), which fixes the gateway's
incorrect 1024-character rejection. The same probe sends Strix-shaped function
tools with 1025-, 1026-, and 2000-character descriptions and verifies that
each reaches the provider payload byte-for-byte; arbitrary truncation is not
used. Provider/model-specific context limits remain provider errors, not a
reason for this gateway to rewrite the request.

## 2026-08-30 Provider-family catalog bound

The 24-route startup budget is a total bound, not a promise to stop after four
routes from the first provider family. The sidecar now defaults
`ORCHESTRATOR_CATALOG_FAMILY_CAP` to 24, allowing an OpenRouter-only discovery
catalog to expose every route within the same bounded preflight budget. An
operator may still set a lower explicit family cap when outage-domain diversity
is more important than route breadth; the generic policy CLI retains its
independent family-cap default.

## 2026-08-30 Startup and serving timeout separation

The ten-second route timeout is a startup-admission budget: a route that does
not answer the bounded readiness probe quickly enough is excluded before
healthz. It must not also bound the real review request. The serving
`ModelClient` now uses the 120-second transport budget already used by the
Noema review gate, while retaining zero retries and the same output-token and
temperature policy. The launcher test constructs both client policies and
asserts their distinct timeouts; it does not infer the contract from duplicate
source text.

## 2026-08-30 Gateway smoke route mode

The exact-head PR #1415 preflight found usable routes, but its gateway smoke
request then defaulted to `auto` orchestration and reached the pinned
server's triage/conduct path. That path returned `invalid_structured_output`
with HTTP 502 even though route admission had succeeded. The smoke request now
sets `orchestration: route`, which exercises the direct virtual-pool path used
by Noema's strict-JSON request and tool-bearing Strix requests and avoids an
unrelated auto-mode triage call. Noema now sends the same mode when its API URL
matches the process-local sidecar origin; unrelated external OpenAI-compatible
URLs retain their original payload. Provider response validation and the
fail-closed treatment of every non-200 response remain unchanged.

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
- The generated bearer is stored in a runner-owned mode-0600 regular file.
  `GITHUB_ENV` carries only that path; every Noema, Strix, OpenCode review, and
  autofix consumer validates ownership, mode, symlink status, size, and line
  structure before reading and masking the bearer inside its own step.
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
  health gate + private token-file creation and path export.
- `scripts/ci/load_contextual_orchestrator_token.sh` — per-step file validation,
  bearer masking, and process-local export for the consuming model command.
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
wrapped both the launcher output and the standalone policy builder output in the
loader-compatible `{"agents": [...]}` envelope and merged exact head
`0f40d415b112ca0055f5db5b2f434788b08f01f1` into protected
`main@24ee38b097dbfc1a895e1199ade48cff36431d05`. The regression is covered by
`tests/test_contextual_orchestrator_review_policy.py` and the sidecar contract.

The earlier PR-target Noema failure remains bootstrap evidence because it ran
the pre-fix trusted base copy. Operational acceptance now requires a fresh
protected-main run that starts the corrected sidecar, passes authenticated
health, and reaches the scanner; queued or cancelled jobs are non-passing.

The first corrected-catalog Noema canary reached authenticated health and the
review gate, but its retained job log showed that exporting the raw bearer via
`GITHUB_ENV` exposed it in the next step's rendered environment header before
that step could mask it. The causal repair therefore exports only a private
token-file path and rehydrates the bearer after each consumer step starts. No
credential value is retained in this record.

Protected-main Strix run `33141468804` then proved that the corrected catalog
reached the sidecar, but LiteLLM rejected the unqualified child model
`orchestrator/free` because its provider was not explicit. The repair keeps the
public/gateway model `contextual-orchestrator/orchestrator/free` and maps only
the scanner child to `openai/orchestrator/free` when its API base is exactly
`http://127.0.0.1:18080/v1`. Missing, empty, or other contextual-orchestrator
API bases fail closed. A fresh protected-main run is still required for
operational acceptance.

PR #1373 merged the model qualification into
`main@8f84b661e468de451ba5c076dc938f342bf52d70`, but retained the raw bearer in
`GITHUB_ENV`. PR #1369 supersedes that credential boundary with file-only
cross-step transport; source integration alone remains insufficient acceptance.
