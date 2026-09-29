### Coverage sandbox installs the base-pinned Rust release

- The coverage image shipped Debian's rustc 1.85, but fast-mlsirm pins 1.97.1 and its
  dependencies need at least 1.90. `maturin build --offline` failed, `_core` never imported, and
  every fast-mlsirm coverage run fell to about 68% against its 100% gate, so no fast-mlsirm pull
  request could reach an APPROVED review. When the base commit pins an exact `1.x.y` release in
  `rust-toolchain(.toml)`, the image now installs it from a SHA-256-verified `rustup-init`
  (minimal profile plus `llvm-tools-preview`) and binds Rust coverage to that release's LLVM tools.
  Repositories without a pin keep the Debian toolchain, and a failed toolchain layer rebuilds the
  previous image. See `docs/doctoring/opencode-rust-coverage-runtime-boundary.md`.
