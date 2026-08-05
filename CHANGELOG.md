# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.
- Added an hourly, single-flight pull-request maintenance workflow that reuses the central scheduler and dispatches a file-scoped OpenCode repair worker.
- Added a dedicated NVIDIA NIM repair worker that requires `NVIDIA_NIM_API_KEY`, uses no Copilot credential or GitHub Models inference, and leaves independent review and merge gates unchanged.
- Added immutable reusable-workflow source resolution through GitHub OIDC workflow-SHA claims, static contract tests, and APA 7th doctoring for the scheduler architecture.

### Fixed

- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
