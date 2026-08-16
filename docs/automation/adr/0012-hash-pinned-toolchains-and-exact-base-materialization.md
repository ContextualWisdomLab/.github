# ADR-0012: Hash-pinned toolchains and exact-base materialization

Status: Accepted
Date: 2026-08-09
Decision owners: CWL supply-chain maintainers

## Context

Central workflows execute across many repositories. Floating actions, packages,
containers, or default-branch source can change between evidence collection and
reproduction. A PR snapshot base SHA can also lag the live protected branch.

## Decision drivers

- Reproducible trusted tooling and dependency resolution.
- Independent source-head and live-base identity.
- Reviewable upgrades with bounded fleet rollout.
- Resistance to dependency substitution and tag movement.

## Alternatives considered

1. **Use latest versions and mutable tags.** Rejected because evidence cannot be
   reproduced or attributed.
2. **Vendor every tool indefinitely.** Rejected due stale vulnerabilities and
   maintenance burden.
3. **Pin immutable action/container revisions and hashed dependency sets; resolve
   live base explicitly.** Selected.

## Decision

Trusted workflow actions and containers use immutable revisions or verified
digests. CI dependencies use reviewed lock/hash manifests and fail on an
unmatched artifact. The executing central workflow commit, target source head,
PR snapshot base, and independently fetched live protected-branch tip are
recorded separately. Mergeability, diff, and operational acceptance use the
live base appropriate to the decision, never an assumed alias.

Dependency and toolchain updates are explicit PRs with provenance, security,
compatibility, and consumer-canary evidence. Generated lock/hash material is
reviewed with its human-readable source declaration.

## Consequences

Runs are more reproducible and supply-chain drift is visible. Upgrades require
regular maintenance, and unavailable pinned artifacts can block a route until a
reviewed replacement is integrated.

## Failure and recovery

Digest/hash/ref mismatch is an integrity failure: do not retry from an
alternative unpinned source. A transient registry transport failure may retry
within budget. Recovery restores the verified artifact or lands a reviewed pin
update and regenerates evidence.

## Security and governance impact

The decision reduces mutable-reference and dependency-confusion attacks.
Credentials used to fetch private artifacts remain scoped and must not enter
untrusted build steps or published evidence.

## Tests and acceptance

- immutable action/container reference checks;
- `--require-hashes` or equivalent dependency installation;
- generated-lock consistency and negative mismatch tests;
- source-head, snapshot-base, live-base, and workflow-source assertions; and
- a protected-main consumer canary for each material toolchain update.

## Migration and rollback

Inventory mutable references, pin the highest-risk trusted paths first, add
contract tests, then migrate remaining dependencies. Rollback returns to the
previous reviewed immutable pin, never to an unbounded latest tag.

## Supersession conditions

Supersede if a verified hermetic build/attestation platform provides stronger
immutable resolution, transparent provenance, and equivalent consumer support.
