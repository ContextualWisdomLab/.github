# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Add a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` invocations, with bounded organization-wide sweeping, immutable current-head dispatch payloads, idempotent receipts, and fail-closed author/repository validation.
- Add hourly bounded review-repair scheduling that preserves the existing reviewer identities and credential chain while continuing non-conflicting maintenance during pending checks or reviews.
- Add a read-only exact-head Python quality workflow that compiles the changed central control-plane modules on Python 3.10 and runs their deterministic Python 3.14 tests with hash-locked tooling, 100% production statement and branch coverage, and 100% production docstrings.

### Security

- Upgrade the central Strix dependency snapshots to `aiohttp==3.14.3`, `cryptography==50.0.0`, and the compatible `pyOpenSSL==26.4.0` closure so the hard dependency gates contain no known affected releases.
- Redact credentials from every sandbox evidence publication sink, including completed and timed-out process output, service log tails, structured and echoed commands, reviewer notes, nested JSON values, and JSON object keys.
- Redact separate sensitive-option values echoed by child processes, concatenated or CamelCase credential-key values, and conservatively classified oversized assignments.
- Bound structured-diagnostic traversal and replace malformed JSON-looking records, over-deep subtrees, or parser/encoder recursion failures with fail-closed redacted evidence instead of crashing or retrying through weaker handling.
- Keep pull-request-controlled code outside the mention-router trust boundary, retain least-privilege workflow permissions, validate reusable workflow sources immutably, and preserve default-branch dependency snapshots for meaningful dependency review.

### Fixed

- Replace quadratic sensitive-assignment rescanning with a bounded forward scan so one long ordinary diagnostic token cannot cause disproportionate log-processing work.
- Scope central JavaScript and TypeScript changed-source coverage to product runtime modules instead of incorrectly requiring Istanbul instrumentation for recognized tool configuration files and bounded `check-*` or `verify-*` repository commands.
- Preserve fail-closed 100% changed-statement, branch, function, and line evidence for runtime modules, including ordinary executable scripts and `src/scripts` modules.
- Preflight trusted-base Python dependency locks atomically so missing, malformed, or unsafe lock inputs fail with bounded diagnostics instead of partially mutating the review environment.

### Documentation

- Add APA 7 doctoring records for trusted review-agent invocation, hourly repair, central security baselines, JavaScript runtime coverage classification, and sandbox command/output redaction boundaries, including verification evidence, modular behavior, limitations, and rollback requirements.
