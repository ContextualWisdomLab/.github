# ADR-0001: Bounded review-agent dispatch and non-authoritative acknowledgements

Status: **Proposed**
Date: 2026-08-12

## Context

The trusted review-agent mention router was exercised against current PR heads
on 2026-08-12. GitHub rejected the OpenCode `repository_dispatch` body because
its `client_payload` contained 14 top-level properties while the API permits at
most 10. A second run reached the dispatch path but failed while creating a
target-repository reaction/acknowledgement with HTTP 403. Treating that UX
failure as a dispatch failure could cause a later sweep to dispatch the same
review again even though the durable central artifact claim already exists.

## Decision

1. Keep the complete exact-head/base/actor/comment/invocation-key claim, but
   place the five fixed review-only policy values under one `review_policy`
   object so every `repository_dispatch.client_payload` remains at or below
   GitHub's ten-property limit.
2. The OpenCode policy remains fail-closed: review triggering is enabled,
   dispatch budget is one, auto-merge is disabled, branch updates are disabled,
   and merge mode is `disabled`. The nested policy is validated by the trusted
   wrapper before the artifact ledger or downstream scheduler is reached.
3. Central dispatch and the durable artifact claim are authoritative. Target
   reactions and acknowledgement comments are best-effort UX signals; a
   permission or transport failure is logged without rethrowing after a
   successful central dispatch.
4. Cross-repository sweeps must use the configured organization token or
   OpenCode installation token. A central `GITHUB_TOKEN` is not treated as a
   sibling-repository credential, and no review or merge authority is inferred
   from a router success.
5. Trusted coverage-image lock preflight must classify a pinned package with no
   binary compatible with the runner interpreter as interpreter incompatibility
   when the resolver reports an explicit available-version list. It may defer
   that candidate to the later coverage stage, while registry, hash, and
   resolver failures remain fatal. The exact contextual-orchestrator #109
   failure at head `216177f` (`atheris==3.0.0`, Python 3.14, only `3.1.0`
   available) is a regression case, not a provider or code-quality excuse.
6. The trusted uv archive fetch keeps its fixed HTTPS origin, no-proxy and
   no-redirect opener, bounded size, and checksum/member verification. A
   transient transport failure may be retried twice at most for HTTP 408, 429,
   5xx gateway/service responses, or socket-level `OSError`; non-retryable HTTP
   status, exhausted retries, redirects, size violations, and integrity failures
   remain blocking. The prior fast-mlsirm #778 exact-head review recorded only
   `trusted uv archive download failed: HTTPError`, so the downloader now retains
   the status code for diagnosis without accepting an alternate origin or
   weakening TLS verification.
7. The exact `OPENCODE_REPOSITORY_DISPATCH_TARGETS` organization variable is a
   security boundary, not a best-effort hint. On 2026-08-12, central dispatch
   validation rejected `ContextualWisdomLab/argos#425` with the expected
   `repository_dispatch authorization rejected target ... absent from the
   configured exact repository allowlist` error, although the organization
   ruleset audit records that `argos` inherits the required workflows. This is
   allowlist drift: the safe repair is to add the intended repository through
   the organization-admin variable change path (using the managed Keyverse/
   admin credential), add an audit assertion that inherited review targets are
   represented in the dispatch allowlist, and retain exact matching. Wildcards,
   implicit organization-wide trust, and weakening the validator are rejected.
   The current repository token lacks the required organization variable scope
   (`HTTP 403 admin:org`), so no unauthorized variable mutation is attempted;
   until the admin update is applied, the affected target remains correctly
   blocked rather than receiving untrusted review dispatch.
8. A push-time Dependabot notice reported five open alerts on the default
   branch, but the read-only alert records bind them to versions already at or
   above each advisory's first patched release: `cryptography==50.0.0` for
   GHSA-g6cj-pr64-35w5/CVE-2026-69247 and `aiohttp==3.14.3` for
   GHSA-cq5v-8q36-5273/CVE-2026-69244,
   GHSA-mfx4-hv73-q22v/CVE-2026-69243, and
   GHSA-mq44-7p77-q5h7/CVE-2026-59881. The pinned hash manifest and source
   requirements agree with those versions, and the current security workflow's
   pip-audit passed. Treat the open alert state as stale GitHub advisory
   materialization until a fresh scan proves otherwise: do not downgrade or
   dismiss the advisories, and rerun the exact-head security scan after any
   dependency-manifest change. If a future scan binds an affected version,
   regenerate both requirements files with uv and commit the generated hashes.

## Consequences

The router can complete a review request when GitHub declines a nonessential
reaction or acknowledgement, preventing duplicate dispatches. A missing
acknowledgement remains visible in logs and does not become approval evidence.
Nested policy decoding adds one explicit workflow boundary, covered by payload
cardinality and exact-claim tests.

The dispatch wrappers also use only GitHub-supported concurrency keys. An
unsupported `queue: max` setting was removed after actionlint rejected it; the
non-cancelling invocation group remains the supported duplicate-control
mechanism.

## Verification

- `tests/test_agent_mention_router.py` verifies the nested policy and ten-field
  limit.
- `tests/test_agent_mention_idempotency.py` verifies target UX failures do not
  redispatch completed agents.
- `tests/test_agent_mention_complete_payload_binding.py` verifies the nested
  policy preserves the exact invocation contract.
- The wrapper workflow reads only `client_payload.review_policy` and forwards a
  ten-property scheduler payload.
- `actionlint` accepts both dispatch wrapper workflows.
- `tests/test_install_base_python_locks.py` covers the Python 3.14/Atheris
  binary-compatibility classification and keeps unclassified resolver/network
  failures fatal.
- Independent current-head review, terminal checks, structured Strix evidence,
  and protected-branch rules remain required before merge.
- The allowlist/ruleset parity audit must be rerun after any organization
  variable update; a missing target is an operational blocker, not review
  approval evidence.
