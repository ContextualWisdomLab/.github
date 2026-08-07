# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- Terminated fatal-provider OpenCode attempts as complete process groups instead of killing only the timeout wrapper, preventing descendant processes from retaining workflow pipes and stalling exact-head coverage evidence after the review launcher exits.
- Bound dependency-review support, Trivy, and Scorecard checkouts to the literal pull-request head repository and SHA; bound Trivy and Scorecard SARIF uploads to the matching `refs/pull/<number>/head` identity; and added permanent dependency-free exact-head regression evidence. Dependency-review availability now fails closed unless the exact base/head comparison returns HTTP 200, discards the untrusted API response body, and never translates 403, 404, transport failure, or another unavailable probe outcome into a green hard gate.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
