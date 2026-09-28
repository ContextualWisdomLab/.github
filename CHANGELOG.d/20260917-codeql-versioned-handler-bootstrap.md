## Changed

- Add a backward-compatible `codeql-scan`/`codeql-scan-v2` protocol bridge to
  the single protected CodeQL dispatch handler. Legacy clients keep their
  exact title, payload, and status context while v2 requires source/base/head
  provenance. Language scans are `actions:read`; one post-matrix settlement
  revalidates the live PR, required run/jobs, handler gate steps, and SARIF
  artifacts before one run-wide rerun. The legacy path has an explicit
  protected-v2/in-flight-drain/zero-caller removal condition. Failed
  credential attempts retain their diagnostics but cannot leak an HTTP error
  body into a later successful API response. Nested rerun authority is bound
  to string schema `"1"`, and settlement stops before mutation when the
  required run reaches attempt 48, preserving capacity below GitHub's limit of
  50 re-runs. ADR-0025.
