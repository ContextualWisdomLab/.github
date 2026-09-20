# Scientific-validation evidence attestation boundary

Status: verifier foundation implemented in PR #2300 for issue #2299. The credentialed signer remains blocked on the reusable-workflow identity prerequisite in #2164; no attestation authority is claimed by #2300 alone.

## Problem

TEPP Validation Evidence now carries content identities for the scientific recovery profile, pre-execution represented chronology, exact-head test receipt, seed manifest, grouped recovery evidence, ordered replication provenance, and per-replication execution artifacts. Those identities are internally coherent but their adapter-supplied origin is not authenticated. A leaf repository must not solve that by embedding a signing key, copying GitHub/OIDC code, or treating another repository's mutable branch as production authority.

The organization control plane therefore owns a separate origin/integrity attestation contract. Scientific meaning remains with TEPP: the control plane must never decide RMSE, bias, coverage, convergence, estimator adequacy, construct validity, or `ScientificallySupported` acceptance.

## Implemented verifier foundation

`scripts/ci/verify_scientific_validation_evidence.py` consumes exactly one bounded regular UTF-8 JSON document as inert data. It requires independent controls for:

- caller/source repository and exact Git SHA;
- workflow run identity and immutable GitHub artifact metadata supplied by the future workflow boundary;
- profile and represented pre-execution chronology SHA-256 identities;
- exact-head receipt identity, exact-head underlying artifact identity, and terminal `passed` state;
- ordered seed-manifest, grouped recovery-evidence, and replication-provenance identities;
- an ordered, unique list of per-replication execution-artifact SHA-256 identities.

It rejects path traversal, symlink/non-regular input, extra or missing artifact members, oversized or invalid UTF-8 JSON, duplicate object keys, non-finite JSON constants, schema drift, malformed digests, exact-head failure states, semantic substitutions, execution-artifact reorder/duplication, and evidence-byte digest mismatch. Output is deterministic canonical JSON written atomically.

The generated predicate type is `https://contextualwisdomlab.org/attestations/scientific-validation/v1`. Its claim is limited to `origin_and_integrity_only`; it explicitly records that psychometric numerical acceptance, RMSE/bias threshold success, construct validity, estimator validity, and production equivalence are outside the attestation claim.

## RED and repair

- Source-level RED `2616480d4af805d28ff4b2c0ff257b005a52d3f4` imported an owner verifier that did not exist and fixed the public fail-closed contract before production implementation.
- Causal verifier repair `6a29685a680b23d8b3af0b684769cfcacdd0d64e` added the bounded inert-data verifier.
- Follow-up test/contract commits `e13885ce7bba9c5400f9fbb6277d47b556718404` and `9f01e4e7b3700a43085b0475c32fd1f5a986e844` repaired nested hostile fixtures and preserved the exact-head terminal state inside the future signed predicate.

The RED was pushed immediately before the repair and is source-level evidence only; no terminal hosted RED is claimed.

## Remaining signer prerequisite

PR #2164 owns the reusable-workflow source-identity repair. Its current head is materially stale relative to protected main and still has two distinct CodeQL blockers: an inherited Python finding already repaired on current protected main, and an Actions GHAS configuration-identity probe that fails with HTTP 403 and remains owned by #2133. The correct path is ordinary non-force reconciliation and fresh exact-head evidence, not copying its mutable implementation into #2300.

After #2164 lands through protected review, #2299 still requires a separate two-phase reusable workflow:

1. an uncredentialed intake job independently re-reads live repository/run/artifact metadata, downloads by immutable artifact ID, and invokes this verifier over the sealed bytes;
2. a credentialed signer job independently re-verifies the same inert evidence, authenticates reusable-workflow source identity from GitHub OIDC, uses an immutable reviewed `actions/attest` pin, and signs only the verified scientific-validation predicate;
3. online and offline verification bind caller repository/source SHA, central signer repository/workflow, predicate type, subject digest, GitHub OIDC issuer/trusted root, and the exact evidence identities above.

No caller/product code may execute in a job holding `id-token: write`, `attestations: write`, or artifact-metadata signing authority.

## Consumer boundary

TEPP #637 is the future consumer ACL. It must wait for a released or immutable-pinned organization verifier/attestation contract and then require a verified receipt before commercial scientific authority is exported. TEPP may retain a pure deterministic scientific decision layer for unit/research evaluation, but must not relabel today's trusted-adapter hashes as cryptographically verified evidence.
