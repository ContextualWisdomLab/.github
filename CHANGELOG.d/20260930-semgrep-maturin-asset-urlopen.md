### Semgrep no longer fails every .github PR on the maturin asset verifier

- `scripts/ci/verify_release_maturin_tool_assets.py` fetches from a fixed
  `https://github.com/PyO3/maturin/releases/download/v1.15.0/` origin, and `verify_assets` admits only
  five literal asset names. The downloader now uses a standard-library opener
  that admits one credential-free HTTPS redirect only from the exact GitHub
  release path to `release-assets.githubusercontent.com`, bounds the response,
  and closes it on every path. It uses neither `urlopen` nor
  `HTTPSConnection`, and carries no `nosemgrep` or `nosec` suppression.
