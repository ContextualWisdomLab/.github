## Added

- Added a strict inert-data verifier foundation for scientific-validation evidence (#2299 / PR #2300). It binds exact repository/head/run identity, profile and pre-execution chronology, exact-head test receipt/artifact state, seed manifest, grouped recovery evidence, ordered replication provenance, and per-replication execution artifact identities into a versioned scientific-validation predicate while explicitly leaving psychometric acceptance to TEPP.
- Hardened verifier output authority in #2301: predicate and manifest destinations must be distinct, must remain outside the sealed evidence root, and must not traverse symlinked/non-directory parent ancestry before publication.
- The verifier is not a signer and does not claim OIDC/Sigstore/GitHub Artifact Attestation authority. Credentialed reusable-workflow signing remains gated on the current #2164 reusable-workflow identity prerequisite and its exact-head review/gates; closed #2133 is not a live prerequisite.
