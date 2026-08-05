# Changelog

All notable changes to the ContextualWisdomLab organization automation control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) when the control plane is tagged.

## [Unreleased]

### Added

- Added an hourly, single-flight pull-request maintenance workflow that reuses the central scheduler and dispatches a file-scoped OpenCode repair worker.
- Added a dedicated NVIDIA NIM repair worker that requires `NVIDIA_NIM_API_KEY`, uses no Copilot credential or GitHub Models inference, and leaves independent review and merge gates unchanged.
- Added immutable reusable-workflow source resolution through GitHub OIDC workflow-SHA claims, static contract tests, and APA 7th doctoring for the scheduler architecture.
