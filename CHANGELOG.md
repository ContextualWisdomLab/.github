# Changelog

All notable changes to the ContextualWisdomLab organization workflow policy are
documented in this file.

The format follows Keep a Changelog, and releaseable changes use Semantic
Versioning where the central workflow repository publishes a versioned release.

## [Unreleased]

### Added

- Import the exact, receipt-verified `contextual-orchestrator` fallback-policy
  module for Noema, OpenCode Agent, and Strix.
- Add a strict shared model manifest with explicit cost tier, repository
  visibility, required credential name, capability, and deterministic priority.
- Add fail-closed supply-chain verification for the vendored source commit and
  Git blob identities.
- Add 74 integration, vendored-policy, and adapter regression tests plus
  operator and doctoring documentation.

### Changed

- Noema now exhausts eligible public NVIDIA NIM free candidates before an
  explicitly configured custom fallback.
- OpenCode Agent now places every eligible NVIDIA NIM, OpenCode free, and
  included-quota GitHub Models candidate before paid provider candidates.
- Strix now uses the same policy order while preserving its existing provider
  transports, report parsing, severity threshold, and reviewer credentials.

### Security

- Private and internal repositories are excluded from public-only hosted trial
  candidates.
- Model pool, vendor receipt, import path, file type, JSON size, duplicate key,
  and source-identity drift fail closed without exposing secret values.
