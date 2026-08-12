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
