## Fixed

- Require a successful GHAS base/head configuration-identity proof and preserved
  SARIF before a clean central CodeQL gate may settle or satisfy an exact required
  run. A failed post-gate identity check can no longer be promoted to GREEN by a
  wake-only fallback.
