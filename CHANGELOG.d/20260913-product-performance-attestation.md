## Added

- Added an organization-owned reusable product-performance evidence attestation workflow with an OIDC-bound reusable-workflow source identity, CWL-only caller boundary, same-run artifact identity checks, versioned custom predicate, GitHub/Sigstore attestation, and retained online/offline verification evidence.
- Added strict data-only result/runtime/fixture verification and a bounded ZIP materializer that authenticates the compressed artifact before extraction and rejects traversal, duplicate names, non-regular entries, unsupported compression, oversized members, and decompression byte-count drift.
- Added exact-head quality contracts for Python 3.10 compatibility, Python 3.14 tests, 100% branch coverage, and 100% production docstring coverage across the performance verifier and materializer.

## Changed

- Structural evidence verification is now recorded as `verification_result: VALID` rather than the ambiguous `result: PASS`; central attestation does not claim that product latency or production-equivalence acceptance passed.
- Reusable performance attestation now fails closed for caller repositories outside `ContextualWisdomLab` before artifact API access.
- Performance evidence no longer relies on `actions/download-artifact` extraction before resource bounds. The workflow first bounds GitHub artifact metadata, limits the ZIP transfer, verifies its artifact digest, and then performs trusted streaming materialization.
