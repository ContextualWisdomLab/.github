# Rust LLVM coverage toolchain boundary

## Status

This record defines the trusted central coverage-image contract for Rust repositories reviewed by the OpenCode dispatch workflow. It is normative for the current repair and does not by itself establish passing evidence. The production workflow, its permanent contract test, and every exact-head check must agree before the pull request may leave Draft state.

## Problem statement

`cargo-llvm-cov` orchestrates Rust source-based coverage by invoking LLVM coverage tools. A pinned `cargo-llvm-cov` executable alone is insufficient when the container does not also provide compatible `llvm-cov` and `llvm-profdata` executables. Missing tools, implicit PATH selection, or incompatible tool versions can turn a coverage gate into an infrastructure failure or, worse, allow an ambient executable to determine evidence semantics.

The trusted image therefore owns the complete coverage toolchain identity. The image must install the Debian `llvm-19` package, bind `LLVM_COV` to `/usr/bin/llvm-cov-19`, bind `LLVM_PROFDATA` to `/usr/bin/llvm-profdata-19`, and verify both paths as executable before downloading or installing the pinned `cargo-llvm-cov` archive. Debian's package manifest lists both versioned executables in `llvm-19`; the workflow must use those explicit paths rather than an unversioned PATH lookup.

The exact variables must be passed into the isolated runtime that executes untrusted repository tests. The runtime must verify both executables again before the first `cargo llvm-cov` invocation. A missing, replaced, non-executable, or unpropagated tool path is a fail-closed coverage setup failure and cannot be treated as not applicable, advisory, queued, or successful evidence.

## Required implementation contract

The trusted coverage workflow must preserve all of the following properties:

1. Keep the existing digest-pinned Python base image and immutable action pins.
2. Install Debian `llvm-19` in the trusted image build.
3. Declare `ENV LLVM_COV=/usr/bin/llvm-cov-19` and `ENV LLVM_PROFDATA=/usr/bin/llvm-profdata-19` after package installation and before the pinned `cargo-llvm-cov` archive installation.
4. Run `test -x "$LLVM_COV"` and `test -x "$LLVM_PROFDATA"` before downloading or extracting the archive.
5. Preserve the reviewed `cargo-llvm-cov` version, archive URL, and SHA-256 verification.
6. Pass `LLVM_COV` and `LLVM_PROFDATA` explicitly through the isolated `docker run` boundary.
7. Re-run both executable checks inside the isolated runtime before the first `cargo llvm-cov` command.
8. Preserve exact-head source materialization, no-persisted-credential checkout, network isolation, least privilege, native-fuzz separation, 100% statement and branch coverage, and public-docstring gates.
9. Treat any setup mismatch as a blocking failure with bounded, redacted diagnostics.

The environment variables are capability bindings, not secrets. They may be included in local diagnostic evidence, but the evidence must identify only the expected paths and command versions. It must not expose repository credentials, provider credentials, GitHub command-file contents, or host-specific filesystem material outside the approved coverage boundary.

## Compatibility rationale

The cargo-llvm-cov project documents `LLVM_COV` and `LLVM_PROFDATA` as explicit overrides and requires the selected LLVM tools to be compatible with the LLVM version used by `rustc`. Its compatibility table places Rust 1.82 through 1.95 with LLVM 19 through 22. The central image currently uses Debian's Rust toolchain together with Debian LLVM 19, so versioned LLVM 19 binaries are the narrowest reproducible system-package boundary for this image.

`llvm-profdata` processes and merges instrumentation profiles; `llvm-cov` reads profile data and instrumented binaries to produce reports or exports. Both are therefore part of the evidence-producing chain. Validating only the wrapper executable does not validate the underlying coverage evidence toolchain.

## Failure semantics

The following conditions block approval and merge:

- Debian `llvm-19` cannot be installed from the image's configured package sources;
- either explicit executable path is absent, is a symlink to an unapproved location, or is not executable;
- either environment variable is absent or changed at the isolated-runtime boundary;
- the second runtime validation occurs after a `cargo llvm-cov` invocation;
- the archive digest, version, or immutable source identity changes without a separate reviewed update;
- a workflow converts the failure into advisory, skipped, not-applicable, or prior-head evidence.

A re-run without a code or infrastructure change cannot cure a deterministic missing-tool contract. Fresh exact-head CI is required after the production workflow is repaired.

## Verification plan

The permanent contract test must assert the package, explicit variables, two ordered executable validations, isolated-runtime propagation, and pre-invocation ordering. The GREEN head must then run the focused contract test, the complete repository test suite, production statement and branch coverage, public-docstring checks, workflow syntax and security-boundary tests, CodeQL and other security gates, packaging and provenance checks, and fresh independent review. No result from the RED head transfers to the GREEN head.

## References

Debian Project. (2026). *File list of package llvm-19 in trixie for amd64*. Debian Packages. https://packages.debian.org/trixie/amd64/llvm-19/filelist

Debian Project. (2026). *Package llvm-19 in trixie*. Debian Packages. https://packages.debian.org/trixie/llvm-19

LLVM Project. (2026). *llvm-cov—Emit coverage information*. LLVM documentation. https://llvm.org/docs/CommandGuide/llvm-cov.html

LLVM Project. (2026). *llvm-profdata—Profile data tool*. LLVM documentation. https://llvm.org/docs/CommandGuide/llvm-profdata.html

Taiki Endo. (2026). *cargo-llvm-cov: Cargo subcommand to use LLVM source-based code coverage* [Computer software]. GitHub. https://github.com/taiki-e/cargo-llvm-cov
