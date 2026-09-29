# Scientific-validation artifact metadata authority

Status: #2314 repair is implemented on PR #2300 but remains unsigned and unreleased. This document narrows one owner-control gap in #2299; it does not grant signer/OIDC or psychometric authority.

## Finding

The scientific-validation verifier already committed GitHub artifact ID, name, and digest, but omitted the REST artifact `size_in_bytes` value required by #2299's live-metadata contract. That omission meant a future signer could not prove that its unsigned receipt represented the complete owner-defined artifact metadata tuple.

Artifact size is independent control-plane metadata. It must come from the same live GitHub artifact record as artifact ID, name, digest, workflow-run identity, and candidate head. It is not the byte length of the extracted scientific evidence JSON member and must not be inferred from that member.

## Contract

`verify_scientific_validation_evidence.py` now requires `--evidence-artifact-size-in-bytes` as a positive decimal integer. The exact value is committed twice:

- predicate evidence: `artifact_size_in_bytes`;
- versioned completion manifest: `evidence_artifact_size_in_bytes`.

`validate_receipt_manifest` strictly validates both values and rejects a manifest whose artifact size differs from the exact predicate bytes committed by `predicate_sha256`. Zero, signed, fractional, exponent-form, and non-decimal values fail closed.

The value remains a string in the local receipt schema so GitHub numeric identifiers and sizes cross process/JSON/CLI boundaries without float coercion. The credentialed workflow may stringify the REST integer only after independently reading and validating the live artifact record.

## RED and repair lineage

- Issue: #2314.
- Source-level RED: `2a8d86c4895419d24389dd36da051bed9fd0bae8`.
- 100% owned-branch quality inclusion: `47ac935c2e92196971048322de84b4b23b1af288`.
- Existing verifier fixture migrations: `29f1b323467adeff8f762f81f37c7f48c2531c5a`, `a4ec7265cfa5564799a11fc054b5d3c76abd4ecb`, `c3628052a301623f8f945f86098b2d4950404b4e`.
- Causal production repair: `a0c75c0eeb4bae31fd1dbeece902d90354901b3c`.
- CHANGELOG currentness: `949ff3649dc235566e8e1008bfb645c25e52dcad`.

No terminal hosted RED or GREEN is claimed from those source commits. Exact-head workflow and review evidence must be generated for the final head before merge or signer consumption.

## Remaining authentication boundary

This repair proves only internal receipt completeness for one independently supplied metadata value. It does not prove that the value came from GitHub. #2164 must first land the reusable-workflow OIDC source-identity prerequisite. #2299 must then re-read the same-run artifact record from GitHub without credentials, cross-bind repository/head/run plus artifact ID/name/size/digest, and let a separately credentialed signer repeat live metadata verification before signing.

TEPP #637 must consume only that released or immutable-pinned authenticated owner contract. TEPP must not import this mutable branch, copy the verifier source, or reinterpret a self-consistent unsigned receipt as cryptographically verified scientific authority.
