# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Move the write-capable scheduled OpenCode PR repair worker from GitHub Models to NVIDIA NIM using only the organization secret `NVIDIA_NIM_API_KEY`, while leaving the independent read-only reviewer workflow and its credential system byte-for-byte unchanged.
- Strip GitHub and OIDC credentials from both OpenCode model subprocesses, pin trusted autofix source to the exact repository-dispatch workflow SHA, deny non-file agent interactions, and fail closed when the NVIDIA credential is absent.

### Changed

- Run the bounded central PR review-repair scheduler at minute 23 of every hour, use a one-hour same-head retry floor, retain a one-dispatch budget and repository-scoped single flight, and bind reusable scheduler implementation to `job.workflow_repository` and `job.workflow_sha` rather than mutable branches or caller-controlled refs.

### Documentation

- Add operator guidance and APA 7 doctoring for the hourly scheduler, immutable workflow source, NVIDIA provider and credential boundary, OpenCode sandbox, modular CWL MSA ownership, verification, and rollback requirements.
