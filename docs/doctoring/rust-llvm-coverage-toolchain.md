# Rust LLVM coverage toolchain boundary

## Status

This record defines the trusted central coverage-image contract for Rust repositories reviewed by the OpenCode dispatch workflow. It is normative for the current repair and does not by itself establish passing evidence. The production workflow, its permanent contract test, and every exact-head check must agree before the pull request may leave Draft state.

## Problem statement

`cargo-llvm-cov` invokes LLVM coverage tools underneath its Cargo interface. A pinned `cargo-llvm-cov` executable is insufficient when the trusted image does not also provide compatible `llvm-cov` and `llvm-profdata` executables. Missing tools, implicit unversioned selection, or incompatible versions can turn a coverage gate into an infrastructure failure or allow ambient tooling to determine evidence semantics.

The trusted image therefore owns the complete toolchain identity. It installs Debian `llvm-19`, binds `LLVM_COV` to `/usr/bin/llvm-cov-19`, binds `LLVM_PROFDATA` to `/usr/bin/llvm-profdata-19`, and verifies both paths as executable before downloading or installing the pinned `cargo-llvm-cov` archive. Debian's package manifest lists both versioned executables in `llvm-19`; the workflow uses those explicit paths instead of an unversioned lookup.

## Runtime propagation boundary

Docker documents that values declared with `ENV` persist in containers created from the resulting image. The OpenCode coverage container is built and then used in the same trusted job. Its low-privilege `run_and_capture` wrapper invokes plain `env`, selectively removes credential-bearing variables, and does not use `env -i`, unset either LLVM variable, or replace either reviewed path. The image bindings therefore survive into the untrusted test process without depending on host environment state.

An earlier RED contract required duplicate `docker run --env` forwarding and a second executable check immediately before `cargo llvm-cov`. That contract was stricter than the implemented trust boundary but did not add an independent security property: host forwarding would permit host state to override the image-owned bindings, while the immutable image already records and preflights both paths. The permanent contract now verifies image ownership, one ordered fail-closed preflight before the cargo-llvm-cov archive, and preservation across the least-privilege wrapper.

## Required implementation contract

The trusted coverage workflow must preserve all of the following properties:

1. Keep the existing digest-pinned base image and immutable action pins.
2. Install Debian `llvm-19` in the trusted image build.
3. Declare `ENV LLVM_COV=/usr/bin/llvm-cov-19` and `ENV LLVM_PROFDATA=/usr/bin/llvm-profdata-19` after package installation and before the pinned `cargo-llvm-cov` archive installation.
4. Run `test -x "$LLVM_COV" && test -x "$LLVM_PROFDATA"` before downloading or extracting that archive.
5. Preserve the reviewed `cargo-llvm-cov` version, archive URL, and SHA-256 verification.
6. Preserve Docker image environment inheritance into the isolated runtime; the low-privilege wrapper must not clear, unset, or replace either LLVM binding.
7. Preserve exact-head source materialization, no-persisted-credential checkout, network isolation, least privilege, Git-configuration isolation, native-fuzz separation, 100% statement and branch coverage, and public-docstring gates.
8. Treat any setup mismatch as a blocking failure with bounded, credential-redacted diagnostics.

The LLVM variables are capability bindings, not secrets. Shareable evidence may identify only the expected versioned paths and command versions. It must not expose repository credentials, provider credentials, GitHub command-file contents, or host-specific filesystem material outside the approved coverage boundary.

## Compatibility rationale

The cargo-llvm-cov project documents `LLVM_COV` and `LLVM_PROFDATA` as explicit overrides and requires selected LLVM tools to be compatible with the LLVM version used by `rustc`. Its compatibility table places Rust 1.82 through 1.95 with LLVM 19 through 22. Debian LLVM 19 is therefore the narrowest reproducible system-package boundary for the current trusted image.

`llvm-profdata` processes and merges instrumentation profiles; `llvm-cov` reads profile data and instrumented binaries to produce reports and exports. Both are part of the evidence-producing chain. Validating only the Cargo wrapper would not validate the underlying coverage toolchain.

## Failure semantics

The following conditions block approval and merge:

- Debian `llvm-19` cannot be installed from the configured package sources;
- either explicit executable path is absent or not executable during the image build;
- either Dockerfile binding is absent, duplicated, or changed;
- the low-privilege runtime wrapper clears, unsets, or replaces either binding;
- executable validation is moved after cargo-llvm-cov archive installation;
- the archive digest, version, or immutable source identity changes without a separately reviewed update;
- any workflow converts the failure into advisory, skipped, not-applicable, queued, or prior-head evidence.

A rerun without a code or infrastructure change cannot cure a deterministic missing-tool contract. Fresh exact-head CI is required after the production workflow changes.

## Verification plan

The permanent contract test asserts the package, unique explicit variables, ordered executable preflight, archive ordering, and low-privilege runtime preservation. The GREEN head must then run the focused contract, complete repository tests, production statement and branch coverage, public-docstring checks, workflow syntax and security-boundary tests, CodeQL and other security gates, packaging and provenance checks, and fresh independent review. No result from the RED head transfers to the GREEN head.

## References

Debian Project. (2026). *File list of package llvm-19 in trixie for amd64*. Debian Packages. https://packages.debian.org/trixie/amd64/llvm-19/filelist

Docker, Inc. (2026). *Dockerfile reference: ENV*. Docker Documentation. https://docs.docker.com/reference/dockerfile/#env

LLVM Project. (2026). *llvm-cov—Emit coverage information*. LLVM documentation. https://llvm.org/docs/CommandGuide/llvm-cov.html

LLVM Project. (2026). *llvm-profdata—Profile data tool*. LLVM documentation. https://llvm.org/docs/CommandGuide/llvm-profdata.html

Endo, T. (2026). *cargo-llvm-cov: Cargo subcommand to use LLVM source-based code coverage* [Computer software]. GitHub. https://github.com/taiki-e/cargo-llvm-cov
