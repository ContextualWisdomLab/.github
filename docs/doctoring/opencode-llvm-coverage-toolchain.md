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

The earlier LLVM repair had been merged into an intermediate feature branch rather than protected `main`; later branch consolidation therefore left the required workflow source without the four toolchain lines. This current-main repair is intentionally limited to restoring those lines, a permanent regression test, this decision record, and the changelog.

## Security and reproducibility contract

- Pull-request content cannot select another LLVM package or executable path.
- The coverage image definition remains default-branch controlled and is built from immutable workflow source.
- `LLVM_COV` and `LLVM_PROFDATA` are set together; partial configuration is rejected.
- Missing executables fail the image build before any pull-request coverage measurement starts.
- Every low-privilege coverage wrapper disables ambient system and global Git configuration before applying the single bounded `/work` safe-directory overlay.
- The image digest, workflow commit SHA, pull-request head SHA, and coverage artifacts remain independently addressable evidence.
- CPU coverage is a correctness gate. GPU execution and parity tests remain separate domain-specific gates and are not represented by LLVM host coverage alone.

This design does not claim formal compliance with a software supply-chain standard. It establishes a narrow, auditable compatibility boundary for deterministic Rust coverage execution.

## Regression contract

The central workflow contract test must continue to prove that:

1. `llvm-19` is installed in the coverage image;
2. `LLVM_COV` names `/usr/bin/llvm-cov-19`;
3. `LLVM_PROFDATA` names `/usr/bin/llvm-profdata-19`;
4. the image build checks both paths before installing or invoking `cargo-llvm-cov`; and
5. the OpenCode approval path remains fail-closed when Rust coverage cannot run; and
6. all three low-privilege wrapper processes isolate system and global Git configuration before the safe-directory overlay.

## References

Debian Project. (2026). *Details of package llvm-19 in trixie*. https://packages.debian.org/trixie/amd64/llvm-19

Endo, T. (2026). *cargo-llvm-cov: Cargo subcommand to easily use LLVM source-based code coverage* [Computer software]. GitHub. https://github.com/taiki-e/cargo-llvm-cov
