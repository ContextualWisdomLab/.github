# Doctoring record: EgressWeave/wardnet adoption audit for contextual-orchestrator (2026-09-03)

- **Date:** 2026-09-03
- **Subject:** backlog item 7 — "각종 통신 보안 이슈는 EgressWeave 그리고 wardnet을 이용해서 처리하는 쪽으로
  이관 바람" (migrate communication-security concerns to EgressWeave and wardnet). This session had
  previously reported item 7 to the user as "손도 안 됨" (zero work started) based on a shallow read; this
  record replaces that with a direct-code investigation of `contextual-orchestrator` (the repo with by far
  the largest outbound-HTTP surface among the org's LLM-facing services).
- **Correction to prior reporting:** the earlier "zero work started" claim was wrong for the wardnet half.
  It stands, with real reasoning now attached, for the EgressWeave half.

## Method

Cloned `ContextualWisdomLab/contextual-orchestrator` fresh and read every outbound-HTTP-related module
directly: `provider_transport.py`, `nim_benchmark.py`, `orchestrator.py`'s `ModelClient` (`_open_provider`,
`_resolve_addresses`, `_connect_validated`, `_provider_url`), and every `wardnet` reference across the repo
(`docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md`, `docs/planning/adrs/0032-*`, `docs/kv-credentials.md`,
`tests/test_camoufox_wardnet_compose.py`, `privacy_policy_analysis.py`, `web_search.py`). Cross-checked
against `EgressWeave`'s published README and its live PyPI listing (`egressweave` 0.1.0, confirmed via
`https://pypi.org/pypi/egressweave/json`).

## Finding 1: wardnet is already integrated — item 7's wardnet half is done, not unstarted

`compose.camoufox-wardnet.yaml` deploys `wardnet` (DNS-pinned egress + authenticated CONNECT proxy) alongside
`camofox-browser` and `camofox-mcp` on isolated Docker networks with no published ports; the browser's only
route out is through wardnet. This is the concrete implementation backing ADR-0123's Camoufox
session-isolation piece (item 14's foundation) and is real, live infrastructure — not a design note. This
session's earlier "wardnet: zero work started" claim for item 7 was wrong; it should have been scoped to
"wardnet is integrated for the one egress path that has it (Camoufox), not for `ModelClient`'s LLM-provider
calls" rather than a blanket zero.

## Finding 2: EgressWeave is NOT adopted for `ModelClient`'s core provider-request path — and the evidence points to this being a considered decision, not an oversight

Three independent pieces of evidence, found in sequence, each narrowing the picture:

1. **`nim_benchmark.py`'s own module docstring states the constraint explicitly:** "the gateway keeps its
   provider-neutral, standard-library-only contract, and this module simply reuses the same stdlib HTTP/KV
   seams to measure the repo's own policies... against a dynamically discovered NIM catalog." This is a
   declared architectural property of the runtime gateway (dependency-minimalism for the org's
   widest-fanout, most latency-sensitive component), not silence on the question.
2. **`ModelClient._open_provider` (orchestrator.py:2190) already implements DNS-pinning by hand, on the live
   runtime path**, with an explicit comment marking it as reviewed: `# The explicit verifying context is the
   security control for this reviewed API` and a `# nosemgrep: python.lang.security.audit.httpsconnection-detected`
   suppression on the one `http.client.HTTPSConnection` construction site — the shape of a change that went
   through review and was deliberately kept, not an unreviewed shortcut. `_resolve_addresses` resolves once
   via `socket.getaddrinfo`; `_connect_validated` connects to that exact resolved address (not the hostname
   again), which is precisely the TOCTOU/DNS-rebinding defense EgressWeave provides (CWE-350) — independently
   arrived at via stdlib.
3. **`ModelClient` must support local providers, and this shapes the whole design.** `_is_local_provider_url`
   / `_provider_url` explicitly allow an `mlx://`-scheme or otherwise local `agent.base_url` (a first-class,
   deliberately supported case per `docs/planning/adrs/0002-explicit-local-mlx-evaluation.md`) alongside
   remote `http(s)://` providers. `agent.base_url` is operator-configured (`ModelAgent` construction), not
   attacker-supplied per-request input — a materially different threat model from EgressWeave's design target
   (arbitrary/attacker-influenced URLs). A library that rejects private/loopback/link-local addresses by
   default — EgressWeave's core SSRF defense — would break local MLX/dev-server routing as a first-class
   supported feature, not an edge case.

**Conclusion: recommend NOT force-adopting EgressWeave into `ModelClient`'s core request path.** The
stdlib-only contract is declared, the DNS-pinning/TOCTOU protection EgressWeave would add already exists
here independently, and EgressWeave's default SSRF posture is actively incompatible with a supported feature
(local providers). This is the same class of finding as this session's earlier ADR-0021 correction and the
naruon#1486 Semgrep false-positive: the right answer is not always "adopt the shared library" or "always
suppress the finding" — sometimes direct code reading shows the existing choice is already correct for its
actual constraints, and forcing an "adoption" would be a regression, not a fix.

## Finding 3: a real, previously-unflagged asymmetry — worth documenting explicitly, not fixing blind

`ModelClient._resolve_addresses` (orchestrator.py:2180) does **not** reject private/loopback/link-local/
multicast/reserved addresses the way `provider_transport.py`'s `validated_public_addresses` (used only by
`nim_benchmark.py`, not the runtime path) does. Given Finding 2's local-provider requirement, this is very
likely intentional — a blanket public-address-only filter on `ModelClient` would break local MLX/dev-server
routing outright — but no ADR or code comment currently records *why* `_resolve_addresses` diverges from
`provider_transport.py`'s stricter sibling, despite both existing in the same repository for a similar
purpose. That absence is a real, if minor, doctoring gap: a future security scanner (or an agent working this
exact backlog item without this investigation's context) could plausibly "fix" `_resolve_addresses` by adding
`provider_transport.py`'s public-address filter, silently breaking every local-provider deployment. **Not
fixed in this record** — this is a comment/documentation addition to a live, actively-used file
(`orchestrator.py`), and per this document's own recommended practice (see `docs/product-technical-gap-baseline.md`'s
standing pattern for this repo), a one-line clarifying comment is safe enough to land directly, but is left
to a dedicated small PR against `contextual-orchestrator` rather than bundled into this documentation-only
change in a different repository.

## Finding 4: `nim_benchmark.py`'s own hand-rolled DNS-pinning (`provider_transport.py`) is a genuine, narrower EgressWeave-adoption candidate — but needs the repo owner's call, not a unilateral swap

`provider_transport.py` (`PinnedHTTPSConnection`, `validated_public_addresses`) duplicates, in ~70 lines of
hand-rolled `http.client`/`socket`/`ssl`/`ipaddress`, close to EgressWeave's exact feature set for the one
case where EgressWeave's default SSRF posture is *not* a problem: `nim_benchmark.py` only ever talks to the
real, non-local NVIDIA NIM cloud endpoint (`NIM_DEFAULT_ENDPOINT`), never a local provider. On the surface
this looks like the item-7 gap the user meant — reinventing what a canonical owner already publishes.

**Not swapped in this record**, for a reason specific to this module: `nim_benchmark.py`'s own docstring
frames "reuses the same stdlib HTTP/KV seams" as being **in service of the benchmark's own validity** — it
exists to measure "the repo's own policies... against a dynamically discovered NIM catalog," and part of
that fidelity may be exercising the same HTTP code shape the gateway itself uses (`http.client`, not
`httpx`), so the benchmark's timing/behavior characteristics stay representative of the real runtime path
rather than a different client's. Swapping this one module to EgressWeave/httpx would fix the
duplication but could silently reduce the benchmark's fidelity as a stand-in for gateway behavior, and this
record cannot confirm from code alone whether that tradeoff was actually weighed when the module was written
or whether the "mirrors the gateway" framing was written for the SSRF/DNS-pinning code specifically or the
whole HTTP stack including method/library choice. **Recommend:** ask `contextual-orchestrator`'s own PR
review / repo owner whether `provider_transport.py`'s DNS-pinning specifically (independent of the
`http.client`-vs-`httpx` question) can be replaced with `egressweave`, or whether the benchmark-fidelity
concern rules that out too. Do not swap unilaterally.

## What this resolves, and what remains open

- **Resolves:** corrects this session's earlier, overly broad "item 7: zero work started" claim — wardnet
  is genuinely integrated (Camoufox egress isolation); EgressWeave's absence from `ModelClient` is a
  considered, evidence-backed decision this record can now cite, not neglect.
- **Does not resolve, deliberately:** no code change lands in this record. Finding 3's clarifying comment
  and Finding 4's `provider_transport.py` question both belong in `contextual-orchestrator`'s own PR flow
  (where its own reviewers/CI/owner can weigh in), not as a unilateral cross-repo edit bundled into a
  `.github` documentation PR.
- **Open, and worth a fresh backlog framing:** if the user's underlying concern is broader than
  `contextual-orchestrator` specifically — e.g., whether OTHER org services (the "Product repos depending on
  1-6" list in `conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md`) make outbound HTTP calls without
  EgressWeave and without contextual-orchestrator's local-provider constraint to justify the gap — that is a
  materially different, still-open audit this record does not cover.

## Audit trail

- `ContextualWisdomLab/contextual-orchestrator` (cloned fresh 2026-09-03): `contextual_orchestrator/provider_transport.py`,
  `contextual_orchestrator/nim_benchmark.py`, `contextual_orchestrator/orchestrator.py` (`ModelClient`,
  lines ~2100-2330), `compose.camoufox-wardnet.yaml`, `docs/adr/0123-web-search-mcp-a2a-gateway-foundation.md`,
  `docs/planning/adrs/0002-explicit-local-mlx-evaluation.md`.
- `ContextualWisdomLab/EgressWeave` `README.md` (main), PyPI `egressweave` 0.1.0.
- `conductor/tracks/003-autonomous-pr-ecosystem-loop/plan.md` (contextual-orchestrator repo) — the existing
  org-wide observation ("`egressweave`, `wardnet` — shared security infra... other services should be
  consuming rather than reinventing") this record narrows to a specific, evidenced finding for one repo.
