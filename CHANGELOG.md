# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.
- Added a permanent exact-head contract workflow for the hourly review-repair scheduler, immutable reusable-workflow source, NVIDIA NIM model boundary, credential isolation, and fail-closed unattended-agent permissions.

### Changed

- Run the bounded PR review-feedback repair scheduler at minute 23 of every hour, reduce the same-head retry floor from 24 hours to one hour, and retain one dispatch per run with repository-scoped single-flight concurrency.
- Use NVIDIA NIM `mistralai/mistral-nemotron` for scheduled repair and `nvidia/nemotron-3-nano-30b-a3b` for bounded helper work instead of GitHub Models in the write-capable autofix worker.

### Fixed

- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Bind reusable scheduler implementation to the validated called-workflow repository, SHA, ref, and file path, and verify the checked-out commit before executing privileged scheduler logic.

### Security

- Bind `NVIDIA_NIM_API_KEY` only to the two OpenCode model execution steps, fail closed when the secret is absent, and remove GitHub and Actions OIDC credentials from both model subprocesses.
- Deny unnecessary non-file OpenCode interactions and preserve the independent read-only reviewer workflow and its credential/model-pool contract byte-for-byte.
- Pin the repository-dispatch autofix helper checkout to the exact workflow-run SHA rather than a moving default branch.

### Documentation

- Added operator and APA 7 doctoring records for the hourly cadence, immutable source identity, NVIDIA NIM provider and secret boundary, model-process credential isolation, modular MSA ownership, verification contract, activation, and rollback.
