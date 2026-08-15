# OpenCode Rust coverage LLVM runtime boundary

## Decision

The trusted OpenCode coverage sandbox binds Rust coverage to the reviewed LLVM
19 executables shipped by Debian's `llvm-19` package:

- `LLVM_COV=/usr/bin/llvm-cov-19`
- `LLVM_PROFDATA=/usr/bin/llvm-profdata-19`

These are compatibility and trust-boundary constants, not caller-selectable
configuration. The coverage image installs `llvm-19`, declares both exact paths,
and fails the image build unless both are executable before the pinned
`cargo-llvm-cov` archive is admitted. The isolated `docker run` passes the same
literal values through the networkless runtime boundary. Inside the container,
`ensure_rust_toolchain()` requires exact string equality and executable files
before the first `cargo llvm-cov` invocation.

The runtime MUST NOT fall back to unversioned `llvm-cov` or `llvm-profdata`, a
host-runner tool, a pull-request-selected path, or a dynamically downloaded LLVM
binary. Missing, changed, or non-executable reviewed paths are coverage-evidence
failures rather than reasons to measure a different toolchain.

NIST SP 800-218 PW.4.1 requires third-party software to come from expected,
trusted sources with integrity verification (Souppaya et al., 2022). The exact
`/usr/bin/llvm-cov-19` and `/usr/bin/llvm-profdata-19` bindings are
producer-selection controls: they select reviewed paths and `test -x` verifies
executability. They do not hash or signature-verify the Debian package or binary.
Package/image hashes, signatures, repository metadata, and attestations are
separate integrity controls and must not be inferred from path equality.

## Why the boundary exists

`cargo-llvm-cov` is a wrapper around Rust's LLVM source-based coverage and
explicitly supports `LLVM_COV` and `LLVM_PROFDATA` as path overrides. Its
current project documentation states that the LLVM tools must be compatible
with the LLVM version used by `rustc`. Allowing ambient `PATH` discovery would
therefore make a runner-image change capable of silently changing the coverage
producer.

Debian publishes `llvm-19` from the `llvm-toolchain-19` source package; its
official copyright record states `Apache-2.0 WITH LLVM-exception`. Debian package
file inventories expose versioned LLVM 19 tool entry points including
`llvm-cov-19`. Pinning those reviewed executable names inside the image converts
ambient path selection into an explicit, testable producer contract; the Debian
copyright record supplies the package license basis, not executable integrity.

## Trust-boundary sequence

```mermaid
flowchart LR
  A["Digest-pinned coverage base image"] --> B["Install Debian llvm-19"]
  B --> C["ENV exact LLVM_COV / LLVM_PROFDATA paths"]
  C --> D["Build-time test -x for both executables"]
  D --> E["Verify pinned cargo-llvm-cov archive"]
  E --> F["docker run --network=none with literal LLVM env values"]
  F --> G["ensure_rust_toolchain exact-value + executable checks"]
  G --> H["cargo llvm-cov"]
```

Each arrow is fail-closed. A later stage does not repair or broaden an earlier
stage's failed trust decision.

## Security and supply-chain implications

The reviewed paths are fixed in trusted central workflow source. Pull-request
content cannot choose an LLVM package, executable path, download origin, or
runtime environment value. The existing coverage sandbox retains
`--network=none`, credential/Git isolation, exact-head/base materialization,
and the separately checksum-pinned `cargo-llvm-cov` archive.

This binding narrows reproducibility risk but does not by itself attest Debian's
whole package supply chain or prove a future Rust toolchain is compatible with
LLVM 19. A future rustc or base-image upgrade must revalidate compatibility and
update this contract, its tests, and CHANGELOG in one reviewed change rather
than silently selecting a different binary.

## Failure and recovery

If the image cannot install `llvm-19`, either reviewed executable is missing or
non-executable, the runtime value differs from the literal reviewed path, or the
isolated runtime does not receive the values, Rust coverage fails closed before
`cargo llvm-cov` runs. The operator should identify whether the failure comes
from Debian package availability, the pinned image/base generation, a central
workflow regression, or an intentional Rust/LLVM compatibility change.

Do not work around the failure by removing the exact-value check, using an
unversioned executable, adding network access to the PR runtime, or accepting a
host-provided path. A deliberate toolchain migration requires fresh authoritative
compatibility evidence and the same RED→GREEN exact-head verification sequence.

## Verification contract

`tests/test_opencode_rust_coverage_toolchain_contract.py` proves that:

1. `llvm-19` is provisioned before the pinned `cargo-llvm-cov` archive;
2. the image binds the two exact LLVM 19 executable paths;
3. image construction verifies both executables;
4. the isolated `docker run` receives both literal values before the coverage
   image argument;
5. `ensure_rust_toolchain()` revalidates exact values and executability before
   Rust coverage; and
6. every exact path named by the permanent quality workflow's
   `pull_request.paths` filter resolves to a repository file, preventing a
   dangling documentation trigger from becoming invisible debt.

The permanent quality workflow runs on Python 3.14, checks out the exact PR head,
executes the focused contract, compiles the test, and applies `git diff --check`.
Repository security and supply-chain workflows remain separate authorities.

## References

Debian Project. (2026). *Package: llvm-19 (1:19.1.7-3~deb12u1), bookworm*.
Debian Packages. Retrieved August 10, 2026, from
https://packages.debian.org/bookworm/llvm-19

Debian Project. (2026). *File list of package llvm-19*. Debian Packages.
Retrieved August 10, 2026, from
https://packages.debian.org/bookworm/amd64/llvm-19/filelist

Debian Project. (2026). *Copyright file for llvm-toolchain-19 19.1.7-20*.
Debian FTP Masters. Retrieved August 15, 2026, from
https://metadata.ftp-master.debian.org/changelogs/main/l/llvm-toolchain-19/llvm-toolchain-19_19.1.7-20_copyright

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Taiki Endo. (2026). *cargo-llvm-cov: Cargo subcommand to use LLVM source-based
code coverage*. GitHub. Retrieved August 10, 2026, from
https://github.com/taiki-e/cargo-llvm-cov
