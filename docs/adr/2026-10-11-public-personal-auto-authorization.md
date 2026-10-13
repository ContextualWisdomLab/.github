# Owner authorization for public personal auto review

## Status

Proposed in ContextualWisdomLab/.github#2607; the maintainer's requested endpoint and model are explicit session instructions.

## Context and decision drivers

The maintainer requested `https://litellm.poinnetworks.net` with model `auto`. Its scoped inference key is configured, but supplier cost metadata is absent. Authentication does not establish zero cost or retention. The existing admission helper consequently blocks the requested public route.

## Considered options

- Require zero-cost evidence for every personal route.
- Admit the explicitly authorized public route while retaining private supplier gates.

## Decision outcome

Use the second option. A maintainer-controlled `PERSONAL_REVIEW_PUBLIC_AUTO_AUTHORIZED=true` may admit only a definitely public target. Its default is false. It is routing authorization, not PR approval or supplier attestation. Private and unknown targets cannot use this exception; private routing still requires zero-cost and zero-retention attestations. The fixed endpoint, literal wire model `auto`, read-only review permissions, source-bound verdict validation, independent reviewer identity and required checks remain unchanged.

## Consequences

Public review can use the requested route without a false cost declaration. Supplier cost remains unknown. Private disclosure and protected merge are still fail-closed; a configured key alone proves neither inference nor approval.
