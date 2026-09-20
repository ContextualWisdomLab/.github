## Added

- Added a strict inert-data verifier foundation for scientific-validation evidence (#2299 / PR #2300). It binds exact repository/head/run identity, profile and pre-execution chronology, exact-head test receipt/artifact state, seed manifest, grouped recovery evidence, ordered replication provenance, and per-replication execution artifact identities into a versioned scientific-validation predicate while explicitly leaving psychometric acceptance to TEPP.
- The verifier is not a signer and does not claim OIDC/Sigstore/GitHub Artifact Attestation authority. Credentialed reusable-workflow signing remains gated on #2164 and the #2133 GHAS configuration-identity boundary.
