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

#2301 additionally hardens the output authority boundary. Predicate and manifest destinations are validated before publication, must be distinct, must remain outside the sealed one-member evidence root, and must not traverse a symlinked or non-directory parent. This prevents a successful verifier invocation from overwriting its own predicate with the manifest, mutating the sealed evidence set after validation, or redirecting trusted-looking output through a symlinked parent.

#2302 hardens input identity against a hash/parse time-of-check-to-time-of-use split. The verifier no longer hashes a pathname and then reopens that pathname for semantic validation. It opens the leaf with `O_NOFOLLOW`, requires the opened descriptor to reference a regular file, reads at most the configured bound plus one byte exactly once into memory, and uses that same byte snapshot for both SHA-256 comparison and strict JSON parsing. A pathname replacement after the descriptor is opened therefore cannot make the verifier attest bytes that differ from the bytes whose semantics it validated. This remains an unsigned local integrity boundary; it is not a provenance signature.

#2303 closes the special-file availability gap introduced by descriptor-first intake. Because the member's type is unknown until `fstat`, a blocking `O_RDONLY` open could wait indefinitely on a FIFO before the regular-file rejection ran. Intake now requests `O_NONBLOCK` together with `O_NOFOLLOW`; regular files behave normally, while FIFOs/devices cannot hold the verifier at `open(2)` before the descriptor-type guard fails closed.

#2304 closes the remaining sealed-root path-authority gap. The verifier now acquires the evidence root by walking each absolute path component through directory descriptors with `O_DIRECTORY | O_NOFOLLOW`, retains the resulting descriptor while checking one-member cardinality, and opens the evidence filename relative to that same descriptor. A concurrent rename/replacement of the root pathname therefore cannot redirect the subsequent evidence read through a new symlinked ancestor. This is still a local filesystem-integrity control; it does not authenticate who created the directory, evidence bytes, or control values.

The generated predicate type is `https://contextualwisdomlab.org/attestations/scientific-validation/v1`. Its claim is limited to `origin_and_integrity_only`; it explicitly records that psychometric numerical acceptance, RMSE/bias threshold success, construct validity, estimator validity, and production equivalence are outside the attestation claim.

## RED and repair

- Source-level RED `2616480d4af805d28ff4b2c0ff257b005a52d3f4` imported an owner verifier that did not exist and fixed the public fail-closed contract before production implementation.
- Causal verifier repair `6a29685a680b23d8b3af0b684769cfcacdd0d64e` added the bounded inert-data verifier.
- Follow-up test/contract commits `e13885ce7bba9c5400f9fbb6277d47b556718404` and `9f01e4e7b3700a43085b0475c32fd1f5a986e844` repaired nested hostile fixtures and preserved the exact-head terminal state inside the future signed predicate.
- #2301 source-level RED is represented by `2205025c99d2e195def5e8173d9c245e642f8548` plus quality-workflow inclusion `41fbde2e370bc5f7565bd5742060cf2cbcffa391`; the predecessor verifier would accept all three unsafe output cases. Causal production repair `c2cc2c10875488632838b1b75540c7529319266c` validates output ancestry/separation from the sealed root before publication.
- #2302 source-level hostile contract `d83e9538d9a27757243f32f4aac42a31a29e6abf` plus quality-workflow inclusion `d5f93acf655d7d02f6b4e2ce1a47dcdade56d6ee` demonstrates that the predecessor can hash malicious bytes A, reopen the same pathname after replacement, and validate benign bytes B. Causal repair `de1e45d56e0ceb4693ebae438b60f4d4d3021c7d` derives digest and semantics from one descriptor-bound byte snapshot. Coverage contract `c077e31f62d1b6df9388b144b232cb1ca86b8603` directly exercises descriptor refusal and the atomic writer's leaf-symlink defense.
- #2303 source-level RED `c68843d88288eed062f3a0941586821e267c92ea` requires the untrusted leaf open flags to include both `O_NOFOLLOW` and `O_NONBLOCK` without using a hanging FIFO fixture. Causal repair `22a0180297fb0ed9dde9bfc5960461bd4bdbef25` adds nonblocking descriptor acquisition while preserving the same byte-snapshot and schema contracts.
- #2304 source-level RED `50edf085aa6a12809e895ae9695fcaeb96666e80` swaps the validated root pathname immediately before evidence intake and requires the read to stay bound to the original directory authority. Causal repair `85e2c07e2d3f49787d8d5b5eff0b08b862bd98ed` introduces the component-wise pinned root descriptor and descriptor-relative leaf open; coverage follow-up `7398c85ce01328782cb3b05d64d85947fc369ce2` exercises symlink-component refusal on descriptor acquisition.

The RED commits were followed immediately by repair commits and no terminal hosted failing receipt is claimed. Exact-head hosted GREEN is also not claimed until the current workflow generation completes.

## Remaining signer prerequisite

PR #2164 owns the reusable-workflow source-identity repair. It has already been ordinary-forward reconciled to current protected `main` as `a20726c1c4a387bba30e5609d550e36d2b0b3087`; closed #2133 is not a live blocker. Its exact-head gates and qualifying independent review still need to complete before the signer path can treat that identity contract as protected authority. The correct path is normal landing/pinned authority, not copying its mutable implementation into #2300.

After #2164 lands through protected review, #2299 still requires a separate two-phase reusable workflow:

1. an uncredentialed intake job independently re-reads live repository/run/artifact metadata, downloads by immutable artifact ID, and invokes this verifier over the sealed bytes;
2. a credentialed signer job independently re-verifies the same inert evidence, authenticates reusable-workflow source identity from GitHub OIDC, uses an immutable reviewed `actions/attest` pin, and signs only the verified scientific-validation predicate;
3. online and offline verification bind caller repository/source SHA, central signer repository/workflow, predicate type, subject digest, GitHub OIDC issuer/trusted root, and the exact evidence identities above.

No caller/product code may execute in a job holding `id-token: write`, `attestations: write`, or artifact-metadata signing authority.

## Consumer boundary

TEPP #637 is the future consumer ACL. It must wait for a released or immutable-pinned organization verifier/attestation contract and then require a verified receipt before commercial scientific authority is exported. TEPP may retain a pure deterministic scientific decision layer for unit/research evaluation, but must not relabel today's trusted-adapter hashes as cryptographically verified evidence.
