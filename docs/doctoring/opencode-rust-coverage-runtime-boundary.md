# OpenCode Rust coverage LLVM runtime boundary

## Decision

The trusted OpenCode coverage sandbox binds Rust coverage to the reviewed LLVM
19 executables shipped by Debian's `llvm-19` package:

- `LLVM_COV=/usr/bin/llvm-cov-19`
- `LLVM_PROFDATA=/usr/bin/llvm-profdata-19`

These are compatibility and trust-boundary constants, not caller-selectable
configuration. The reviewed helper `scripts/ci/ensure_rust_llvm19.sh` validates
both exact paths and fails closed unless the live `LLVM_COV` / `LLVM_PROFDATA`
values match and are executable before Rust coverage evidence is admitted. The
actual environment binding is owned by
`.github/workflows/opencode-review-dispatch.yml`, through its Dockerfile `ENV`
declarations and the isolated container's `docker run --env` arguments. If that
workflow changes, its `REVIEW_DISPATCH_BLOB_SHA` pin must change with it; this
does not rewrite the review-agent key system.

The runtime MUST NOT fall back to unversioned `llvm-cov` or `llvm-profdata`, a
host-runner tool, a pull-request-selected path, or a dynamically downloaded LLVM
binary. Missing, changed, or non-executable reviewed paths are coverage-evidence
failures rather than reasons to measure a different toolchain.

Rust dependency materialization follows the same boundary. The trusted
`coverage-source-tree` job runs `cargo fetch --locked` from a runner-owned,
neutral `HOME`/`CARGO_HOME`, with GitHub credentials removed, and copies only
Cargo's content-addressed `registry/` and `git/` directories into the
tree-local sandbox home. Prefetch and runtime force Cargo's `git` registry
protocol so runner and container Cargo versions consume the same cache layout.
The PR execution container remains `--network=none` and uses
`CARGO_NET_OFFLINE=true`; a reserved `.opencode-sandbox-home` path in the PR
tree is rejected before the Cargo-availability branch so PR content cannot be
mixed with the trusted cache even when the runner lacks Cargo. Prefetch failure
is retained as a fail-closed offline coverage failure.

NIST SP 800-218 PW.4.1 covers acquiring and maintaining third-party software
from expected, trusted sources and reviewing its provenance (Souppaya et al.,
2022). PW.4.4 covers verifying the integrity of acquired components. The exact
`/usr/bin/llvm-cov-19` and `/usr/bin/llvm-profdata-19` bindings are
producer-selection controls: they select reviewed paths and `test -x` verifies
executability. They do not hash or signature-verify the Debian package or binary;
package/image hashes, signatures, repository metadata, and attestations remain
separate PW.4.4 integrity controls and must not be inferred from path equality.

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
  A["Reviewed helper scripts/ci/ensure_rust_llvm19.sh"] --> B["Default LLVM_COV_PATH / LLVM_PROFDATA_PATH"]
  B --> C["Require live LLVM_COV and LLVM_PROFDATA equality"]
  C --> D["Require both paths executable"]
  D --> E["Fail closed before cargo llvm-cov"]
  F["Hashed opencode-review-dispatch.yml"] --> G["Unchanged review-agent key blob"]
  H["Trusted cargo fetch: neutral HOME/CARGO_HOME + git protocol"] --> I["registry/ + git/ cache only"]
  I --> J["PR coverage: CARGO_NET_OFFLINE=true + --network=none"]
```

Each arrow is fail-closed. A later stage does not repair or broaden an earlier
stage's failed trust decision.

## Security and supply-chain implications

The reviewed paths are fixed in trusted central workflow source. Pull-request
content cannot choose an LLVM package, executable path, download origin, or
runtime environment value. The existing coverage sandbox retains
`--network=none`, credential/Git isolation, exact-head/base materialization,
and the separately checksum-pinned `cargo-llvm-cov` archive. Cargo dependency
prefetch is performed before PR code execution, without the target repository's
configuration or GitHub credentials, and only content-addressed caches cross
into the sandbox. Both sides force the git registry protocol to avoid a sparse
versus git index-layout mismatch between runner and container Cargo versions.

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

1. the helper defaults both reviewed LLVM 19 executable paths;
2. the helper requires live `LLVM_COV` / `LLVM_PROFDATA` equality with those
   paths;
3. the helper requires both paths to be executable and exits `1` on mismatch;
4. the helper does not mention unversioned `llvm-cov` / `llvm-profdata`; and
5. locked Rust dependencies are prefetched before the networkless sandbox,
   with neutral Cargo configuration, credential removal, and the same forced
   registry protocol on both sides; and
6. every exact path named by the permanent quality workflow's
   `pull_request.paths` filter resolves to a repository file, including the
   helper, preventing a dangling documentation trigger from becoming
   invisible debt.

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
