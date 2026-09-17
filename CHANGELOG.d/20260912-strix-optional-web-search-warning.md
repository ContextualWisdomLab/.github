### Fixed

- Keep completed Strix scans valid when their report contains only the exact
  upstream warning for missing optional `EXA_API_KEY`, `PERPLEXITY_API_KEY`, or
  combined web-search credentials. Unknown warnings remain fail-closed, and raw
  report artifacts remain unchanged for audit evidence.
