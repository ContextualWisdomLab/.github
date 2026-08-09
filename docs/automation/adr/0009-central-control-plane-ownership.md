# ADR-0009 — Central control-plane ownership and thin leaf callers

Status: active_pr

## Context

Copying automation into products causes policy drift, duplicated secrets, incompatible evidence and slow incident repair. Products still need independent operation and product-owned tests.

## Drivers

One reviewed organization control plane, stable explicit interfaces, modular products, and limited failure domains.

## Alternatives

1. Copy full workflows into every repository. 2. Centralize all product behavior. 3. Keep reusable policy centrally and use thin leaf callers/contracts.

## Decision

Choose option 3. The central repository owns cross-repository governance semantics; leaf repositories own product code, repository-specific gates and bounded caller inputs.

## Consequences

Central changes have broad leverage and require stronger compatibility testing. Leaf repositories remain independently operable when optional central/model services are unavailable.

## Failure and recovery

A central regression is isolated by versioned provenance and caller rollback. A leaf-specific defect remains in the leaf lease.

## Security and governance impact

Central interfaces enforce least privilege, exact caller identity and no privilege self-enablement from PR content.

## Tests and acceptance

Source-repository, fork, dispatch-envelope, secret-interface and compatibility tests cover central and leaf sides; protected-main consumers prove integration.

## Migration and rollback

Publish versioned interfaces, migrate leaf callers incrementally, and retain the last compatible pin during rollback.

## Supersession conditions

Supersede only if a new ownership model preserves single-source policy, modular product operation and explicit trust boundaries.
