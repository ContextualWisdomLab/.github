### Coverage sandbox builds PyO3/maturin extensions offline before pytest

- `maturin==1.15.0` (MIT/Apache-2.0) is added to `requirements-opencode-review-ci.txt` /
  `requirements-opencode-review-ci-hashes.txt` (hashes verified against PyPI JSON metadata for the
  exact release), closing the last gap `materialize_base_rust_dependencies.py` (#2222, #2223) left
  open: the base commit's Cargo dependency graph was vendored for `cargo llvm-cov`, but nothing
  ever built the PyO3 extension itself, so `python3 -m coverage run -m pytest` kept failing
  collection with `ImportError: cannot import name '_core'` on 8 of the last 10 fast-mlsirm
  fallbacks (fast-mlsirm#1907). `.github/workflows/opencode-review-dispatch.yml`'s
  `run_python_test_coverage` now calls a new `build_maturin_extension_if_needed` helper for every
  tracked Python project whose `pyproject.toml` declares `build-backend = "maturin"`: it runs
  `maturin build --offline --release` against the vendored Cargo dependencies with
  `CARGO_NET_OFFLINE=true CARGO_BUILD_JOBS=1` (the sandbox is memory-constrained), then
  `pip install --user --no-index --no-deps` installs the built wheel before pytest runs, entirely
  inside the existing `--network=none` sandbox. `tests/test_maturin_offline_build_contract.py`
  proves both halves of the claim against a real PyO3 fixture crate: the vendored-offline build
  produces an importable `_core` extension, and a dependency only a pull request's head added
  (never seen by the base-commit materializer) is never fetched -- the offline build fails closed
  on the missing crate instead of reaching the network. Refs fast-mlsirm#1907.
