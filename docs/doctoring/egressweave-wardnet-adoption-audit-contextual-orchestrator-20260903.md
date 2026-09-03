# Doctoring record: EgressWeave/wardnet adoption audit for contextual-orchestrator (2026-09-03)

- **Date:** 2026-09-03 (revised twice same day — see "Correction" and "Correction 2" below)
- **Subject:** backlog item 7 — "각종 통신 보안 이슈는 EgressWeave 그리고 wardnet을 이용해서 처리하는 쪽으로
  이관 바람" (migrate communication-security concerns to EgressWeave and wardnet). This session had
  previously reported item 7 to the user as "손도 안 됨" (zero work started) based on a shallow read; a first
  pass of this record replaced that with a direct-code investigation of `contextual-orchestrator` but reached
  a wrong conclusion on the central question, corrected below.

## Correction — 2026-09-03, same day, before merge

The first version of this record concluded "recommend NOT force-adopting EgressWeave... EgressWeave's default
SSRF posture is actively incompatible with a supported feature (local providers)." **The user challenged this
directly ("버그네" — "that's a bug") and was right.** A follow-up investigation (9-agent workflow: one deep
read of EgressWeave's actual source against its own test suite, one full feature audit of `ModelClient`'s
transport, one synthesis) found the original claim was based on EgressWeave's README/PyPI listing alone,
never checked EgressWeave's own policy API for an override, and was wrong: EgressWeave ships a documented,
tested "local-development exception" (`EgressPolicy(allow_local=True)`) built for exactly this scenario. The
corrected findings replace Finding 2 and Finding 3 below; Findings 1 and 4 are unaffected. This also surfaced
several genuine, previously-unverified gaps in `ModelClient`'s own transport (Finding 5) that EgressWeave
would close — the opposite of this record's original, too-confident dismissal.

## Correction 2 — 2026-09-03, same day, review feedback on this PR

Devin's automated review on this PR (comment IDs `3922894674`, `3923057235`, `3923057436`, `3923057593`)
correctly challenged the *first correction's* own redesign sketch on three technical points, each verified
directly against EgressWeave's source rather than taken on faith:

1. **"`build_egress_sync_client` resolves aliases internally and exposes no resolver seam."** Confirmed:
   `ValidatedEgressURL` (`validation.py:55-75`) is a frozen, `init=False` dataclass whose `__init__`
   unconditionally raises `TypeError("ValidatedEgressURL objects must come from a validation function")`;
   results are only ever produced by `_make_validated_egress_url`, which stamps an HMAC integrity signature
   (`_validated_egress_url_signature`) no external caller can forge. There is no code-level hook to hand the
   library a pre-resolved address for an alias. The real mechanism is one level down: `_resolve_all_global_addresses`
   calls plain `socket.getaddrinfo(hostname, port, ...)` — the OS resolver — so an alias only works if it is a
   *genuinely resolvable hostname* (an `/etc/hosts` entry, a container DNS alias, or equivalent) that
   `getaddrinfo` itself resolves to `127.0.0.1`, not an in-process Python-level override "in front of"
   EgressWeave. The original sketch's "small resolver in front of EgressWeave's own DNS resolution" wording
   was imprecise in exactly the way Devin flagged.
2. **"Calling `build_egress_sync_client` per request discards pooling and repeats DNS validation... needs
   bounded, origin-specific clients with deterministic closure."** Correct as a critique of adopting
   `build_egress_sync_client`/the full `httpx.Client` transport for `ModelClient`. This is resolved by not
   adopting that entry point at all — see the revised Finding 2 recommendation below, which uses only the
   validation function and leaves `ModelClient`'s existing (already poolless, open-per-request)
   `http.client` transport untouched. No client-lifecycle question is introduced.
3. **"EgressWeave caps connect, read, write, and pool waits through one transport. It cannot govern only
   connection establishment as proposed without redesign."** Confirmed at the source: `EgressTimeoutPolicy`
   (`timeout_policy.py:26-66`) is a frozen dataclass with four independent phase ceilings
   (`connect_timeout_seconds`, `read_timeout_seconds`, `write_timeout_seconds`, `pool_timeout_seconds`, each
   default `5.0`), and `__post_init__` unconditionally rejects a non-finite value for *any* of them
   ("`{field} must be finite and greater than zero`") — so a caller cannot request an unbounded read/write
   timeout, and that ceiling is baked into the SAME `_PinnedEgressTransport` that performs the pinned
   connect-and-read as one atomic operation (splitting "validate/connect" from "read/write" across two
   different clients would reopen exactly the DNS-rebinding window pinning exists to close). The original
   sketch's claim that EgressWeave could be "scoped narrowly to the connection-establishment phase only" while
   keeping request/response timeout separate does not hold for `build_egress_sync_client`. **It does hold**
   for the narrower `validate_egress_url_details`-only integration adopted in the revised Finding 2: that
   function has no `httpx` dependency at all and governs only its own independent, always-finite
   `dns_timeout_seconds` — it never touches request read/write timeouts, so there is nothing to "scope" or
   reconcile with `ModelClient.timeout` in the first place.

Findings 2 and 5 below are revised to reflect this narrower, verified integration. The corrected
recommendation is unaffected in substance — EgressWeave adoption remains not blocked by the local-provider
requirement — but the *mechanism* is now the validation function, not the full client builder.

## Method

Cloned `ContextualWisdomLab/contextual-orchestrator` fresh and read every outbound-HTTP-related module
directly: `provider_transport.py`, `nim_benchmark.py`, `orchestrator.py`'s `ModelClient` (`_open_provider`,
`_resolve_addresses`, `_validate_provider`, `_connect_validated`, `_provider_url`, `_send`, `_send_raw`,
`_stream_send`, `_read_bounded_response`), and every `wardnet` reference across the repo. For the correction,
also cloned `ContextualWisdomLab/EgressWeave` fresh and read its actual `src/egressweave/validation.py` and
`policy.py` source (not just its README), its `docs/security-model.md`, and its passing test suite
(`tests/test_allow_local_security.py`, `tests/test_exact_local_allowlist.py`) — including an executed
proof-of-concept against the real library confirming the allowlist behavior end to end.

## Finding 1: wardnet is already integrated — item 7's wardnet half is done, not unstarted

`compose.camoufox-wardnet.yaml` deploys `wardnet` (DNS-pinned egress + authenticated CONNECT proxy) alongside
`camofox-browser` and `camofox-mcp` on isolated Docker networks with no published ports; the browser's only
route out is through wardnet. This is the concrete implementation backing ADR-0123's Camoufox
session-isolation piece (item 14's foundation) and is real, live infrastructure — not a design note. This
session's earlier "wardnet: zero work started" claim for item 7 was wrong; it should have been scoped to
"wardnet is integrated for the one egress path that has it (Camoufox), not for `ModelClient`'s LLM-provider
calls" rather than a blanket zero.

## Finding 2 (corrected): EgressWeave's allowlist API already supports the local-provider case — the earlier "incompatible" conclusion was an incomplete-investigation error, not a correct finding

EgressWeave ships a first-class, documented, tested "local-development exception," not an edge case it
happens to miss:

- **`EgressPolicy(..., allow_local=True)`** plus a bare single-label hostname in `allowed_hosts` lets that one
  host resolve to loopback/RFC1918/RFC4193 space while every other (dotted, public) hostname in the *same
  policy instance* still requires a genuinely global address. Evidence, read directly from source:
  `src/egressweave/validation.py:167-202` (`_validate_global_address`) — the "reject non-global address"
  check is the **fallthrough** branch, not an unconditional gate; two branches ahead of it
  (`_is_local_dev_host`, `_is_allowlisted_local_host`) can return successfully for a private/loopback address
  first. `src/egressweave/policy.py:462-475` (`EgressPolicy.is_allowlisted_local_host`) is the exact gating
  condition: `self.allow_local and normalized in self.allowed_hosts and "." not in normalized`.
- **Directly documented and tested for this exact scenario.** `docs/security-model.md:40-68`'s
  "Local-development exception" section gives the canonical worked example —
  `EgressPolicy.from_hosts("ollama", allow_local=True, allowed_ports={11434})` — a local-LLM server, the same
  class of thing `contextual-orchestrator`'s `mlx://`/`local://` providers are.
  `tests/test_allow_local_security.py:59-66` and `tests/test_exact_local_allowlist.py:98-117` are passing
  tests asserting exactly this behavior end to end (through the public `validate_egress_url_details()` API).
- **Independently reproduced in this investigation**, not just cited: built
  `EgressPolicy.from_authorities([("api.example.com", 443), ("ollama", 11434)], allow_local=True)` against the
  real source and confirmed in the same policy instance: `api.example.com` rejects `127.0.0.1` and accepts a
  genuine global address; `ollama` accepts both `127.0.0.1` and a private RFC1918 address; end-to-end URL
  validation correctly pinned a local URL to `127.0.0.1` and a remote URL to its public address
  *simultaneously*.

**The one place the original worry survives, in a narrower and differently-reasoned form:**
`contextual-orchestrator`'s real `ModelAgent.base_url` values (`examples/agents.mlx.json`,
`examples/agents.local.json`) are raw loopback **IP literals** — `mlx://127.0.0.1:8080/v1`,
`local://127.0.0.1:18000/v1`, `local://127.0.0.1:1234/v1` — and EgressWeave's allowlist unconditionally
rejects an IP literal as the authority hostname even under `allow_local=True`
(`_is_ip_literal`/`_looks_like_ip_literal`, `validation.py:358-367`, proven by
`_validate_remote_authority_is_allowed`). So today's exact `base_url` strings cannot be handed to EgressWeave
verbatim. **That is an integration task (alias local providers to a bare single-label hostname instead of a
raw IP), not a library incompatibility** — the distinction the original version of this record collapsed.

**Corrected recommendation, revised again after review (see "Correction 2" below):** EgressWeave adoption for
`ModelClient`'s provider-request path is *not* blocked by the local-provider requirement. The right-sized
integration uses only EgressWeave's **validation function**
(`egressweave.validate_egress_url_details(url, policy=policy) -> ValidatedEgressURL | None`, a pure DNS+SSRF
check with its own independent `dns_timeout_seconds` and zero dependency on `httpx`/request execution — see
`src/egressweave/validation.py`'s imports) as a drop-in replacement for `ModelClient._validate_provider`'s
~40 lines of hand-rolled `socket.getaddrinfo`/`ipaddress` validation, returning the same
`(hostname, port, addresses)` shape `_connect_validated` already consumes today. `ModelClient`'s own
`http.client`-based transport, retry/backoff, streaming, and timeout handling are otherwise **unchanged** —
this deliberately does *not* adopt `build_egress_sync_client`'s full `httpx.Client` (see Finding 5's
correction for why). This is a genuine, scoped implementation task for `contextual-orchestrator`'s own repo —
not done in this record (see "What remains open" below) — not a recommendation against adoption.

## Finding 3 (retracted): the "asymmetry" in the original record was a misreading — `_validate_provider` already does the conditional filtering

The original Finding 3 claimed `ModelClient._resolve_addresses` "does not reject private/loopback/link-local
addresses" on the runtime path and treated this as a real, if minor, undocumented gap. **This was wrong** —
it looked only at the raw DNS-pinning helper (`_resolve_addresses`, `orchestrator.py:2180`, which indeed does
no filtering) and missed that its actual caller on every live request path, `_validate_provider`
(`orchestrator.py:2766-2804`), *does* apply exactly the conditional filtering the original Finding 3 said was
missing: for a confirmed local provider (`_is_local_provider_url`), every resolved address must be loopback
(rejects otherwise); for a remote provider, every resolved address must be public/global (rejects
private/loopback/link-local/multicast/reserved — the identical rule `provider_transport.py`'s
`validated_public_addresses` applies, just implemented inline rather than via a shared helper). There is no
undocumented asymmetry between `ModelClient` and `provider_transport.py` on this axis; both already enforce
the same policy shape. This finding is retracted, not merely revised.

## Finding 4: `nim_benchmark.py`'s own hand-rolled DNS-pinning (`provider_transport.py`) is a genuine, narrower EgressWeave-adoption candidate — but needs the repo owner's call, not a unilateral swap

`provider_transport.py` (`PinnedHTTPSConnection`, `validated_public_addresses`) duplicates, in ~70 lines of
hand-rolled `http.client`/`socket`/`ssl`/`ipaddress`, close to EgressWeave's exact feature set for the one
case where EgressWeave's default SSRF posture is *not* a problem: `nim_benchmark.py` only ever talks to the
real, non-local NVIDIA NIM cloud endpoint (`NIM_DEFAULT_ENDPOINT`), never a local provider.

**Not swapped in this record**, for a reason specific to this module: `nim_benchmark.py`'s own docstring
frames "reuses the same stdlib HTTP/KV seams" as being **in service of the benchmark's own validity** —
exercising the same HTTP code shape the gateway itself uses so the benchmark's timing/behavior characteristics
stay representative of the real runtime path. Swapping this module to EgressWeave would fix the duplication
but could reduce benchmark fidelity; this record cannot confirm from code alone whether that tradeoff was
weighed when the module was written. **Recommend:** ask `contextual-orchestrator`'s own PR review / repo
owner before swapping this one, independent of Finding 2's corrected conclusion about the main path.

## Finding 5 (new, from the correction pass): EgressWeave would close several genuine, previously-unverified gaps in `ModelClient`'s own transport

A full feature audit of `ModelClient`'s transport (not just the SSRF/DNS-pinning question) found real,
evidenced gaps EgressWeave's feature set would close — the opposite of the original record's dismissal:

- **Response size bounding (CWE-400) is absent on the primary chat path.** `_send`
  (`orchestrator.py:2096-2129`) and `_send_raw` (`2679-2703`) do an unbounded `response.read()` with no
  `Content-Length` check or byte cap — despite a sound bounded-read pattern (`_read_bounded_response`,
  `3015-3028`) already existing elsewhere in the same file and being wired into `proxy_get_bytes`/
  `proxy_upload`/`proxy_get_json`/`proxy_delete_json`, just not the chat path.
- **Response size bounding is also absent on the streaming (SSE) path** (`_stream_send`, `2316-2394`: iterates
  the raw `HTTPResponse` with no cap on total bytes, line count, or elapsed duration) and on `_batch_upload`
  (`2969-2990`), `_batch_raw` (`3030-3038`, no `max_bytes` parameter at all), and `proxy_send_bytes`
  (`2516-2538`).
- **No outbound request size pre-flight bounding** — oversized requests are only caught reactively after the
  provider itself returns HTTP 413, with no local budget check before dispatch.
- **No phase-split timeout enforcement.** `_open_provider` applies one scalar timeout uniformly to
  connect/send/recv via `http.client`'s single `socket.settimeout()`; there is no independent connect-timeout
  vs. read-timeout vs. write-timeout the way EgressWeave documents.
- **HTTP method allowlisting is a source-code convention, not a runtime-enforced boundary.** Every call site
  hardcodes a literal method, but `_open_provider` performs no runtime check of `request.get_method()`
  against an allowlist.
- **Redirect rejection is an emergent side effect, not a stated, tested policy.** Using raw `http.client`
  instead of `urllib`'s opener chain means no `HTTPRedirectHandler` is ever installed, so a 3xx is never
  auto-followed today — but this is incidental to the transport library choice (zero hits for
  "redirect"/3xx/`Location` anywhere in the file), not a documented, tested guarantee; a future switch to a
  higher-level client (`requests`/`httpx`) could silently reintroduce auto-redirect-following. Notably,
  `model_discovery.py` (a *different*, non-`ModelClient` module) already has an explicit
  `_TrustedDiscoveryRedirectHandler` for its own discovery/policy-crawl client — proving the team already
  knows and uses this pattern elsewhere, just not on `ModelClient`'s own egress path.
- **No explicit `Accept-Encoding: identity` / no-transparent-decompression policy.** Today's absence of a
  decompression-bomb path is incidental to `http.client` not auto-negotiating compression, not an intentional
  "force identity" design decision the way EgressWeave documents it.

**Timeout-model tension (revised in Correction 2, now source-verified both ways) — real for the full client
builder, moot for the validation-only integration this record now recommends.** This org has a standing "no
default Application/Agent/Gateway timeout ceiling" directive (confirmed live in this same worktree's own
recent history: commit `69e80bd`, "remove the 300s LLM_TIMEOUT cap" from `strix.yml`), and `ModelClient.timeout`
is architecturally the same shape — an unbounded, fully overridable default, not an enforced ceiling.
**Verified this is a real conflict for `build_egress_sync_client`:** `EgressTimeoutPolicy`
(`timeout_policy.py:26-66`) unconditionally requires all four phase timeouts (connect/read/write/pool) to be
finite and positive — `__post_init__` raises `ValueError` on any non-finite value — so a `ModelClient` calling
`chat()` with `timeout=None` (fully supported and used today) could never be honored by that transport; EgressWeave
would force some finite ceiling onto every request regardless of operator intent. **But this tension only
applies if `build_egress_sync_client`'s full transport is adopted**, which Correction 2 above already ruled
out for other reasons (client lifecycle, no resolver seam for the local-provider alias). The recommended
narrower integration — calling only `validate_egress_url_details(url, policy=policy)` as a validation utility
— has zero request-timeout entanglement (confirmed: `validation.py` never imports `httpx`; the function's only
timing constraint is its own independent, always-finite `dns_timeout_seconds`, a bounded DNS lookup deadline
that is uncontroversial and unrelated to how long an LLM inference call may run). So for the integration this
record actually recommends, there is nothing to reconcile: `ModelClient.timeout`, retries, backoff, and
candidate failover stay exactly where they are today, fully operator-configurable including unbounded.

**Docs cross-check, one risk flagged:** `docs/planning/adrs/0032-model-group-cost-aware-discovery.md:53-56`
states "Wardnet, not this Python service, owns destination policy, DNS pinning, redirects, and body limits" —
but this is scoped to a *separate*, delegated outbound-fetch path used only for policy/ZDR-privacy-page
crawling via Wardnet's proxy, **not** to `ModelClient`'s own provider chat/completions egress (which
implements its own DNS pinning/validation directly, as Findings 2/3 confirm). If a future reader applies that
ADR sentence to the audited path here, that would be a misreading worth catching.

## What this resolves, and what remains open

- **Resolves:** corrects the earlier "item 7: zero work started" claim (wardnet is genuinely integrated) and,
  after the same-day correction above, replaces an incorrect "EgressWeave is incompatible" conclusion with a
  verified one: EgressWeave's local-provider exception is real and load-bearing, the actual blocker is a
  narrow IP-literal-vs-hostname integration detail, and EgressWeave would close several genuine, previously
  unverified transport gaps (response-size bounding, phase-split timeouts, method-allowlist enforcement,
  explicit redirect/encoding policy).
- **Does not resolve, deliberately:** no code change lands in this record. The EgressWeave integration sketch
  (Finding 2), Finding 4's `provider_transport.py` question, and Finding 5's individual gaps all belong in
  `contextual-orchestrator`'s own PR flow (where its own reviewers/CI/owner can weigh in and where a
  security-critical transport rewrite deserves dedicated regression tests) — not as a unilateral cross-repo
  edit bundled into a `.github` documentation PR.
- **Open, and worth a fresh backlog framing:** if the user's underlying concern is broader than
  `contextual-orchestrator` specifically — e.g., whether OTHER org services (the "Product repos depending on
  1-6" list in `conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md`) make outbound HTTP calls without
  EgressWeave — that is a materially different, still-open audit this record does not cover.

## Audit trail

- `ContextualWisdomLab/contextual-orchestrator` (cloned fresh 2026-09-03):
  `contextual_orchestrator/provider_transport.py`, `contextual_orchestrator/nim_benchmark.py`,
  `contextual_orchestrator/orchestrator.py` (`ModelClient`: `_open_provider`, `_resolve_addresses`,
  `_validate_provider` lines 2766-2804, `_connect_validated`, `_send`/`_send_raw`/`_stream_send`,
  `_read_bounded_response`), `compose.camoufox-wardnet.yaml`,
  `docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md`,
  `docs/planning/adrs/0002-explicit-local-mlx-evaluation.md`,
  `docs/planning/adrs/0032-model-group-cost-aware-discovery.md`, `examples/agents.mlx.json`,
  `examples/agents.local.json`, `docs/product-technical-gap-baseline.md:2664-2682` (related,
  already-known `TaskOrchestrator._invoke` overall-deadline gap).
- `ContextualWisdomLab/EgressWeave` (cloned fresh for the correction pass): `src/egressweave/validation.py`,
  `src/egressweave/policy.py`, `docs/security-model.md`, `tests/test_allow_local_security.py`,
  `tests/test_exact_local_allowlist.py`; plus an executed proof-of-concept against the real source. For
  Correction 2 (Devin review feedback), additionally: `src/egressweave/sync_transport.py`
  (`build_egress_sync_client`, `build_pinned_https_client`), `src/egressweave/timeout_policy.py`
  (`EgressTimeoutPolicy`), and `src/egressweave/__init__.py`'s `__all__` (confirming
  `validate_egress_url_details` is a public, documented standalone entry point, not an internal helper).
  PyPI `egressweave` 0.1.0.
- `conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md` (contextual-orchestrator repo) — the existing
  org-wide observation ("`egressweave`, `wardnet` — shared security infra... other services should be
  consuming rather than reinventing") this record narrows to a specific, evidenced finding for one repo.
