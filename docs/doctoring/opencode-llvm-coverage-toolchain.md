# OpenCode LLVM coverage toolchain decision

## Decision

The central OpenCode coverage image installs Debian Trixie's `llvm-19` package and explicitly exports:

```text
LLVM_COV=/usr/bin/llvm-cov-19
LLVM_PROFDATA=/usr/bin/llvm-profdata-19
```

The image build fails unless both paths are executable. This is required because the image uses Debian-packaged `rustc` rather than a rustup-managed toolchain, so `llvm-tools-preview` is not an available installation path.

## Evidence and compatibility boundary

`cargo-llvm-cov` documents `LLVM_COV` and `LLVM_PROFDATA` as the overrides to use when a Rust toolchain is installed outside rustup. It also requires the selected tools to be compatible with the LLVM version used by `rustc`. Its published compatibility table maps Rust 1.82–1.95 to LLVM 19–22. The central image therefore selects LLVM 19 as the lowest compatible family for its supported Rust range and keeps the two binary paths explicit rather than relying on an unversioned system default.

Debian Trixie publishes `llvm-19` from the `llvm-toolchain-19` source package. The workflow installs the package from the pinned Debian image repositories and verifies the exact versioned executable paths during image construction.

## Observed regression

DiskSage pull request 133 exact head `b7f980d265713d5ffb84f744ce454589e3d410ea` passed its repository Test, Release, Security Scan, and SAST workflows. Central OpenCode run `31037491215`, job `92413313900`, then failed before Rust test execution with `failed to find llvm-tools-preview`. The failure reproduced the previously diagnosed central-toolchain defect rather than a DiskSage production-code failure.

The earlier LLVM repair had been merged into an intermediate feature branch rather than protected `main`; later branch consolidation therefore left the required workflow source without the four toolchain lines. This current-main repair is intentionally limited to restoring those lines, permanent regression contracts, this decision record, the changelog, and the exact-head quality workflow that executes both focused and repository-wide evidence.

## Security and reproducibility contract

- Pull-request content cannot select another LLVM package or executable path.
- The coverage image definition remains default-branch controlled and is built from immutable workflow source.
- `LLVM_COV` and `LLVM_PROFDATA` are set together; partial configuration is rejected.
- Missing executables fail the image build before any pull-request coverage measurement starts.
- Every low-privilege coverage wrapper disables ambient system and global Git configuration before applying the single bounded `/work` safe-directory overlay.
- Both quality jobs check out `github.event.pull_request.head.sha`, refuse merge-tree or stale-head evidence, and preserve no repository credentials.
- The fast contract job installs no packages and evaluates no pull-request-selected dependency manifest.
- The full repository job installs only the repository's SHA-256 hash-locked quality requirements, then runs every test plus the configured 100% branch coverage and production docstring gates.
- The image digest, workflow commit SHA, pull-request head SHA, and coverage artifacts remain independently addressable evidence.
- CPU coverage is a correctness gate. GPU execution and parity tests remain separate domain-specific gates and are not represented by LLVM host coverage alone.

This design does not claim formal compliance with a software supply-chain standard. It establishes a narrow, auditable compatibility boundary for deterministic Rust coverage execution.

## Durable exact-head verification

`.github/workflows/opencode-coverage-toolchain-quality-ci.yml` is the repository-owned acceptance path for this contract. It runs whenever the trusted coverage workflow, either quality workflow contract, this decision record, the hash-locked quality requirements, `pyproject.toml`, or the changelog changes.

The first job checks out the exact pull-request head SHA, verifies that Git materialized that SHA rather than GitHub's generated merge revision, discovers every dependency-free `test_` function in the focused contract module, compiles the module, and fails if the test process changes the worktree. It never installs packages.

Only after that job passes, a separate approved-environment job checks out and revalidates the same exact head, installs the repository-owned hash-locked quality toolchain, runs `pytest` across the complete `tests` directory under the configured 100% branch-coverage gate, enforces 100% production docstrings, and compiles all production CI modules and repository tests. This separation preserves a minimal early fail-closed contract while preventing focused tests from substituting for full repository acceptance.

## Regression contract

The central workflow contract test must continue to prove that:

1. `llvm-19` is installed in the coverage image;
2. `LLVM_COV` names `/usr/bin/llvm-cov-19`;
3. `LLVM_PROFDATA` names `/usr/bin/llvm-profdata-19`;
4. the image build checks both paths before installing or invoking `cargo-llvm-cov`;
5. the OpenCode approval path remains fail-closed when Rust coverage cannot run;
6. all three low-privilege wrapper processes isolate system and global Git configuration before the safe-directory overlay;
7. the focused quality job is exact-head bound, credential-free, and dependency-free; and
8. the dependent full repository job is exact-head bound, uses the SHA-256 hash-locked quality toolchain, and runs the complete test, branch-coverage, docstring, and compilation gates.

## References

Debian Project. (2026). *Details of package llvm-19 in trixie*. https://packages.debian.org/trixie/amd64/llvm-19

Endo, T. (2026). *cargo-llvm-cov: Cargo subcommand to easily use LLVM source-based code coverage* [Computer software]. GitHub. https://github.com/taiki-e/cargo-llvm-cov
