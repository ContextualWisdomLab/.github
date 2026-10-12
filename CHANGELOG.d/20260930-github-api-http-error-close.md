## Fixed

- Close file-like `HTTPError` responses in the central CodeQL, Strix, Noema,
  Pingora, review-preflight, Pages, and sandbox-readiness clients after bounded
  status/telemetry extraction, preventing Python 3.14 resource leaks without
  permitting redirects, suppressing warnings, or weakening bearer-token
  authority checks; cap CodeQL diagnostic error-body reads at 400 bytes.
