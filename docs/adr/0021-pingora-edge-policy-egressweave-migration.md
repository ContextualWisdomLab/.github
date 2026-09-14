# ADR-0021: Migrate pingora_edge_policy.py's GitHub REST calls to EgressWeave

- **Status:** Accepted (adapter landed; cutover pending)
- **Date:** 2026-09-02
- **Decision owners:** ContextualWisdomLab platform and product maintainers

## Context

The owner directed that ad-hoc, repo-local communication-security handling be
migrated to route through `EgressWeave` and `wardnet` instead of being
reimplemented per repository. `scripts/ci/pingora_edge_policy.py` — the
required-workflow script that enforces ADR-0019's Pingora-only edge runtime
policy — is exactly such a case: its `_github_open_json` helper hand-rolls a
`urllib.request`-based GitHub REST client with its own origin pin
(`_validate_github_api_url`, `api.github.com` only), redirect rejection
(`NoRedirectHandler`), and a bounded response read
(`MAX_RESPONSE_BYTES = 16_777_216`). `EgressWeave` is a dedicated SSRF- and
DNS-rebinding-safe outbound HTTP client for exactly this class of problem,
and its default `max_response_bytes` (16 MiB) matches this script's own bound
exactly.

Two things stood in the way of a direct swap:

1. **PyPI/source parity gap.** The `egressweave` package published on PyPI
   (0.1.0) ships only an async client (`policy.py` + `transport.py` +
   `validation.py`) — no synchronous client, no body-size bounding, no
   timeout policy. `pingora_edge_policy.py` is synchronous and needs the
   16 MiB response bound; EgressWeave's protected-`main` source (`0.3.0`) has
   both, but that source is not yet on PyPI.
2. **Hash-pin-only CI dependency discipline.** This repository's
   `scripts/ci/*.py` install nothing beyond the standard library today; every
   pinned dependency this repository does install comes from
   `pip install --require-hashes` against a `uv pip compile
   --generate-hashes`-produced lock file. A VCS-sourced requirement cannot
   satisfy `--require-hashes`, so EgressWeave's current source could not be
   adopted as an ordinary dependency without a new PyPI release.

EgressWeave's own `docs/adr/0005-cwl-central-github-ci-consumer-integration.md`
records the accepted resolution: consumers in this position vendor an
exact-commit submodule pin of EgressWeave's protected `main`, add
EgressWeave's own ordinary PyPI runtime dependencies (`httpx==0.28.1`,
`httpcore==1.0.9`, `idna`) to their own hash-pinned requirements, and land a
narrow adapter additively. This ADR applies that pattern here. `wardnet` was
considered and is not applicable: it is a Rust inbound gateway/WAF/IDS/SOC
control plane, not an outbound-HTTP-client SSRF library, and
`pingora_edge_policy.py`'s problem is outbound-request safety.

## Decision

1. Vendor EgressWeave as a git submodule at `vendor/egressweave`, pinned to
   commit `978f65172a23d69a9d92bf58bbcbe363a459238f` (never a branch or tag).
2. Add `httpx`/`httpcore`/`idna` — EgressWeave's own ordinary, independently
   published dependencies — to a dedicated hash-pinned
   `requirements-pingora-egress-ci.txt` /
   `requirements-pingora-egress-ci-hashes.txt` pair, following this
   repository's existing one-file-per-CI-concern convention (bandit,
   pip-audit, strix, OpenCode review each already have their own).
3. Add `scripts/ci/pingora_edge_egress_opener.py`: a narrow adapter exposing
   `github_open_json(url, token) -> object`, the exact `OpenJson` callable
   shape `pingora_edge_policy.py`'s `evaluate_pull_request(..., opener=...)`
   already accepts. The adapter owns no security logic beyond constructing
   an `EgressPolicy.from_hosts("api.github.com", allowed_methods={"GET"})`
   and mapping `EgressNotAllowedError`/HTTP failures to one generic
   `EgressAdapterError` — mirroring `PolicyError`'s existing generic-failure
   contract in `pingora_edge_policy.py`.
4. Gate that adapter in its own `pingora-edge-egress-opener-quality-ci.yml`
   workflow (checks out submodules, installs both hash-pinned requirement
   sets, runs the adapter's dedicated test suite at 100% statement+branch
   coverage, then re-runs this repository's full `pytest tests` suite as a
   cross-file regression check, matching the pattern
   `trusted-uv-materializer-quality-ci.yml` already established for a
   similarly narrow addition).
5. Omit `scripts/ci/pingora_edge_egress_opener.py` from the root
   `pyproject.toml` coverage config (mirroring the existing
   `contextual_orchestrator_review_launcher.py` precedent), and make its test
   module (`tests/test_pingora_edge_egress_opener.py`) skip — not error —
   when the submodule is not initialized. This repository's central OpenCode
   review-coverage pipeline materializes a PR's merge tree with
   `--no-recurse-submodules` (`opencode-review-dispatch.yml`, "Coverage merge
   tree materialization"); without this skip guard, every PR touching this
   repository would fail test collection the moment this adapter's test file
   existed, regardless of whether that PR touches the adapter at all.
6. **This ADR's own scope stops at landing a proven, independently-tested
   adapter.** `pingora_edge_policy.py`'s live default (`_github_open_json`)
   is unchanged in this change; the required-workflow step
   ("Enforce Cloudflare Pingora edge policy" in `opencode-review.yml`) keeps
   calling the existing `urllib`-based implementation. Flipping that default
   to `pingora_edge_egress_opener.github_open_json` and deleting
   `NoRedirectHandler`/`_validate_github_api_url`/the manual
   `MAX_RESPONSE_BYTES` check is a follow-up change, gated on this PR's own
   CI (including the dedicated workflow in item 4) confirming the new path
   is a verified equivalent-or-stronger replacement in this repository's real
   `pull_request_target` execution context — not only in local tests. This
   sequencing follows this organization's "prove the new path, then remove
   the old one" convention for security-relevant migrations, rather than a
   single rip-and-replace of a currently-working required-workflow gate.

## Consequences

### Positive

- `pingora_edge_policy.py`'s SSRF/redirect/response-size protection is on a
  path to being centrally owned and tested by EgressWeave instead of
  independently reimplemented and independently capable of drifting.
- The vendored pin is an explicit, reviewable line in this PR's diff.
- Landing the adapter without flipping the live default keeps the existing,
  currently-working control in place through this PR; nothing about the
  required workflow's behavior changes until a follow-up PR's own CI proves
  the replacement.

### Costs and risks

- A second, not-yet-cut-over implementation now exists in the repository
  until the follow-up cutover PR lands and the old `urllib`-based code is
  deleted.
- The submodule pin must be bumped (and re-reviewed) deliberately to receive
  EgressWeave security fixes; it will not update automatically.
- `vendor/egressweave` and the new dependency set add real, if small,
  supply-chain surface (`httpx`, `httpcore`, `idna`, `certifi`, `h11`,
  `anyio`) to a `scripts/ci/*.py` family that is otherwise pure standard
  library today — accepted here because that surface is already vetted and
  hash-pinned elsewhere in this repository (`requirements-strix-ci-hashes.txt`
  already pins `httpx==0.28.1`/`httpcore==1.0.9`) and is scoped to the one new
  adapter, not to every existing script.

## Alternatives rejected

- **Reimplement redirect/size bounding a second time against EgressWeave's
  PyPI 0.1.0 API:** would still duplicate security logic (async-only, no
  size bounding) and regress the existing 16 MiB response bound. Rejected.
- **`pip install git+https://...@<sha>`:** `pip install --require-hashes`
  rejects VCS requirements outright; would force dropping hash-pinning for
  this one dependency. Rejected.
- **Cut the live default over to EgressWeave in this same PR:** the
  currently-running required-workflow gate would go from zero third-party
  dependencies to a five-package dependency chain in one step, without this
  repository's own CI having exercised that exact `pull_request_target`
  execution path first. Rejected in favor of the additive, two-step sequence
  in Decision item 6.
- **Wait for EgressWeave to publish a PyPI release with parity before
  starting:** blocks this migration on a separately governed release
  process outside this PR's scope. Rejected; see EgressWeave ADR 0005.

## Validation

`scripts/ci/pingora_edge_egress_opener.py` has 100% statement and branch
coverage and 100% docstring coverage under
`pingora-edge-egress-opener-quality-ci.yml`, including tests for a missing
token, a non-GitHub-API URL (wrong scheme and wrong host), a successful
parsed-JSON response, an `EgressNotAllowedError` policy denial, a non-2xx
HTTP status, a generic transport error, a malformed-JSON response, and both
branches of the lazily-built process-wide client cache. A dedicated test
confirms the real (non-fake) client construction path pins the
`api.github.com` authority using EgressWeave's own DNS-monkeypatch test
convention. The full repository `pytest tests` suite passes with this change
applied.
