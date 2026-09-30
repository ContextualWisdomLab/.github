### Rust coverage that only exceeds the per-command cap is disclosed as not measured

- fast-mlsirm's `mlsirm-core` suite runs for tens of minutes under `cargo llvm-cov` (56 min for
  the workspace on a 4-job M-series host), past the sandbox's 900 s per-command cap, so every
  Rust-changing PR failed coverage evidence on the timeout alone. For the Rust coverage commands
  only, exit 124 (`timeout`) is now reported as `NOT MEASURED` and listed in the Coverage Decision,
  instead of counting as a failure. Test failures, below-threshold coverage, kills (137) and every
  other command still fail.
