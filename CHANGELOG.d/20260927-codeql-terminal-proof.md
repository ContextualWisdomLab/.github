## Fixed

- Require a successful GHAS base/head configuration-identity proof and preserved
  SARIF before a clean central CodeQL gate may settle or satisfy an exact required
  run. A failed post-gate identity check can no longer be promoted to GREEN by a
  wake-only fallback.
- Bind CodeQL terminal receipts to the live base, required run, head, and merge
  source through the v2 dispatch protocol, preventing a trusted but stale commit
  status from satisfying a retargeted or later required run.
