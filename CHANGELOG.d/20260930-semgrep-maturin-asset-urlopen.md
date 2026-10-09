### Semgrep no longer fails every .github PR on the maturin asset verifier

- `scripts/ci/verify_release_maturin_tool_assets.py` fetches from a fixed
  `https://github.com/PyO3/maturin/releases/download/v1.15.0/` origin, and `verify_assets` admits only
  five literal asset names, but `p/default`'s `dynamic-urllib-use-detected` flagged the call on
  main and failed Semgrep on every PR. The call now carries the repository's standard reasoned
  `nosemgrep`/`nosec B310` suppression.
