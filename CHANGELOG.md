# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added a permanent test-first Rust coverage-toolchain contract requiring Debian LLVM 19, explicit versioned `LLVM_COV` and `LLVM_PROFDATA` bindings, executable validation before cargo-llvm-cov installation, explicit propagation through the isolated runtime, and a second fail-closed validation before the first coverage invocation.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- Bind the write-capable OpenCode PR autofix and conflict-resolution worker exclusively to NVIDIA NIM through `NVIDIA_NIM_API_KEY`, fail closed when that model credential is absent, disable implicit GitHub Models provider discovery, and preserve the existing repository-write identity chain separately from model inference.
- Provision Debian LLVM 19 in the trusted OpenCode coverage image, bind the versioned `llvm-cov` and `llvm-profdata` executables, and preflight both paths before installing the pinned cargo-llvm-cov archive; isolated-runtime propagation and pre-invocation revalidation remain required by the permanent contract before this change can merge.
- Distinguish conservatively proven type-only TypeScript changes from executable code when `coverage-final.json` omits the changed file, permitting only multiline `import type`, balanced `interface`, comment, and delimiter lines while preserving fail-closed missing-instrumentation errors for mixed or runtime-looking changes.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Keep the native Atheris fuzz-engine lock in dedicated repository fuzz workflows instead of installing it in the generic OpenCode coverage image; immutable hash-pinned property and regression test locks remain eligible for central coverage materialization.
- Publish bounded, credential-redacted OpenCode coverage setup diagnostics through one shared helper, redact every `Authorization` value without relying on an enumerated authentication scheme, add a hash-locked Python 3.10 TOML compatibility dependency, and preserve exact-head validation.
- Reject unsafe Strix source-directory overrides before path joining, including traversal, absolute, nested, symlink-expanding, glob, control-character, oversized, and excessive-cardinality values while retaining validated internationalized direct directory names.
- Restore the protected-main OpenCode Git-configuration isolation and NVIDIA NIM fallback contracts, remove transient pull-request repair workflows and encoded patch payloads, and add a permanent repository-wide branch-writer absence gate.

### Documentation

- Document the OpenCode PR autofix NVIDIA NIM provider/credential boundary, fail-closed secret handling, unchanged GitHub write-identity chain, regression contract, rollback rules, and current official NVIDIA, OpenCode, and GitHub references in APA 7th format.
- Document the fail-closed Rust LLVM coverage boundary with APA 7 references to Debian's LLVM 19 package manifest, cargo-llvm-cov's compatibility and environment-variable contract, and the official LLVM `llvm-cov` and `llvm-profdata` command guides.
- Extend the coverage diagnostics doctoring record with the type-erasure trust boundary, Inkspan reproduction, RED/GREEN exact-head evidence, fail-closed limitations, and APA 7 references to official TypeScript documentation.
- Add APA 7 doctoring records for coverage diagnostics, the generic coverage/native fuzz-engine dependency boundary, the trusted-uv materializer, and the Strix NVIDIA fallback and source-directory boundary, including exact-base trust models, verification fixtures, limitations, and rollback requirements.
