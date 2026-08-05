# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.
- Added a permanent exact-head contract workflow for the hourly review-repair scheduler, immutable reusable-workflow source, NVIDIA NIM model boundary, credential isolation, and fail-closed unattended-agent permissions.
- Added a dedicated Clearfolio hourly caller that invokes the product-neutral central scheduler with the exact repository, protected base branch, one-dispatch budget, one-hour retry floor, single-flight concurrency, and only the established scheduler credentials.

### Changed

- Run the bounded Clearfolio PR review-feedback repair caller at minute 23 of every hour while keeping the shared scheduler free of product-specific timers and repository names for modular reuse by naruon, contextual-orchestrator, and other CWL services.
- Use NVIDIA NIM `mistralai/mistral-nemotron` for scheduled repair and `nvidia/nemotron-3-nano-30b-a3b` for bounded helper work instead of GitHub Models in the write-capable autofix worker.

### Fixed

- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Bind reusable scheduler implementation to the validated called-workflow repository, SHA, ref, and file path, and verify the checked-out commit before executing privileged scheduler logic.
- Removed the ambiguous central-repository schedule fallback that could scan `.github` instead of Clearfolio when no external variable was configured; the active product caller now names Clearfolio explicitly while the reusable engine retains caller and dispatch overrides.

### Security

- Bind `NVIDIA_NIM_API_KEY` only to the two OpenCode model execution steps, fail closed when the secret is absent, and remove GitHub and Actions OIDC credentials from both model subprocesses.
- Deny unnecessary non-file OpenCode interactions and preserve the independent read-only reviewer workflow and its credential/model-pool contract byte-for-byte.
- Pin the repository-dispatch autofix helper checkout to the exact workflow-run SHA rather than a moving default branch.
- Pass only `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` from the Clearfolio schedule caller; do not use `secrets: inherit` and do not expose the NVIDIA model credential to the queue-scanning workflow.

### Documentation

- Added operator and APA 7 doctoring records for the hourly cadence, immutable source identity, NVIDIA NIM provider and secret boundary, model-process credential isolation, modular MSA ownership, product-specific caller activation, verification contract, and rollback.
