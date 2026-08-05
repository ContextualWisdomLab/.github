# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Keep the native Atheris fuzz-engine lock in dedicated repository fuzz workflows instead of installing it in the generic OpenCode coverage image; immutable hash-pinned property and regression test locks remain eligible for central coverage materialization.
- Publish bounded, credential-redacted OpenCode coverage setup diagnostics through one shared helper and preserve exact-head, Rust dependency-context, and deterministic LLVM coverage-toolchain contracts.
- Reject unsafe Strix source-directory overrides before path joining, including traversal, absolute, nested, symlink-expanding, glob, control-character, oversized, and excessive-cardinality values while retaining validated internationalized direct directory names.

### Documentation

- Add APA 7 doctoring records for coverage diagnostics, the generic coverage/native fuzz-engine dependency boundary, the trusted-uv materializer, the Strix NVIDIA fallback and source-directory boundary, and the LLVM coverage toolchain, including exact-base trust models, verification fixtures, limitations, and rollback requirements.
