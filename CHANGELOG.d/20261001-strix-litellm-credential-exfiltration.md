### Shared Strix LiteLLM security floor

- Pinned LiteLLM 1.94.3 in the Strix source input and regenerated the complete
  hash lock after exact-head `pip-audit` found CVE-2026-84377 in 1.94.1.
- Added a source/lock parity regression contract and preserved the stacked Noema
  document-reader transitive security repair without copying its implementation.
