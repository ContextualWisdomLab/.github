# Scientific-validation evidence I/O failure boundary

Status: source-level RED and causal repair are on PR #2300 under issue #2323. This remains an unsigned verifier boundary; credentialed authority is still owned by #2299 and gated by #2164.

## Problem

The sealed-evidence reader already opened one leaf with `O_NOFOLLOW | O_NONBLOCK`, verified regular-file type by descriptor, capped the read at 16 MiB + 1 byte, and reused the exact byte snapshot for digest and semantic validation. The initial `os.open()` failure was normalized into `EvidenceError`, but `os.fstat()` or buffered `read()` could still raise raw `OSError` after the descriptor had been acquired.

The verifier CLI treats `EvidenceError` as the stable invalid-evidence boundary. A post-open storage or descriptor fault could therefore escape as a traceback or platform-dependent process failure before scientific semantics were evaluated. That makes operational failure classification depend on Python/runtime behavior rather than the owner contract.

## Decision

`_read_evidence_once()` now preserves deliberate `EvidenceError` outcomes and normalizes other post-open metadata/read `OSError` failures to `EvidenceError("evidence read failed: <leaf>")`. Descriptor closure remains in `finally`.

The repair does not reopen the path, add retries, weaken the 16 MiB ceiling, or infer scientific acceptance from I/O success. `O_NOFOLLOW | O_NONBLOCK`, descriptor-relative root authority, one-read byte identity, SHA-256 comparison, and strict semantic parsing are unchanged.

## Alternatives rejected

- Catching `OSError` only in CLI `main()` was rejected because library callers would retain an inconsistent raw-exception contract.
- Retrying the read was rejected because it could consume a different storage snapshot and would weaken the one-open/one-byte-snapshot invariant.
- Catching `Exception` was rejected because it would hide programming defects and owner-generated `EvidenceError` diagnostics.

## Evidence and traceability

- Issue: #2323.
- Source-level RED: `475b6bd83a016d45131f7f49434038c93ac3f926` adds a real regular-file hostile fixture whose post-open stream read raises `OSError`; predecessor behavior leaks that raw exception.
- Causal repair: `e630dc6bc2d42c9aa69fad60667121def6314d8c` normalizes post-open metadata/read `OSError` while preserving existing explicit `EvidenceError` paths.
- Changelog: `c1454588a5b32305f2395806b990fe7f91ec7614`.
- Production API: `scripts/ci/verify_scientific_validation_evidence.py::_read_evidence_once`.
- Hostile contract: `tests/test_scientific_validation_evidence_single_read.py::test_descriptor_reader_normalizes_post_open_read_failure`.

Hosted exact-head GREEN is not claimed until the current PR #2300 generation receives a runner and all required checks settle. No predecessor check result transfers to a newer commit.

## Boundary and follow-up

This change authenticates nothing. It only makes local inert-data intake fail closed deterministically. #2299 still owns live GitHub run/artifact re-resolution, OIDC-backed signing, immutable reviewed attestation, and online/offline bundle verification. TEPP #637 must consume only the eventual released or immutable-pinned owner contract and must continue to own psychometric meaning, RMSE/bias/coverage/convergence acceptance, and `ScientificallySupported` promotion.
