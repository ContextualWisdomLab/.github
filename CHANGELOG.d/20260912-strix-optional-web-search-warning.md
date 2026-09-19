### Fixed

- Keep completed Strix scans valid when their report contains only the exact
  upstream warning for missing optional `EXA_API_KEY`, `PERPLEXITY_API_KEY`, or
  combined web-search credentials. Unknown warnings remain fail-closed; only the
  trusted classification log is sanitized before failure-signal evaluation.
