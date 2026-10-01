## Fixed

- Rust coverage on the self-hosted OpenCode runner can find `cargo` again. The
  runner keeps it in `~/.cargo/bin`, which its service does not put on PATH,
  so every Rust coverage gate failed and no fast-mlsirm review could approve.
  A missing toolchain is now reported as such instead of a bare exception name.
- Coverage jobs remove coverage images older than two hours before measuring.
  Runs dispatched before per-run cleanup existed had filled the runner disk.
