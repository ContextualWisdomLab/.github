# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Upgrade the central Strix dependency snapshots to `aiohttp==3.14.3`, `cryptography==50.0.0`, and the compatible `pyOpenSSL==26.4.0` closure so the hard dependency gates contain no known affected releases.
- Redact credentials from every sandbox evidence publication sink, including completed and timed-out process output, service log tails, commands, reviewer notes, nested JSON values, and JSON object keys.
- Continuously drain sandbox child stdout/stderr into fixed-size final-suffix buffers, terminate isolated process groups on overflow, and persist only bounded service evidence so repository output cannot exhaust parent memory or runner log storage before redaction.

### Changed

- Add explicit 1 MiB per-stream command and 4 MiB per-service log budgets, stable output-limit exit code `123`, result-envelope limit evidence, and bounded seek-from-end service tails while preserving timeout `124` and readiness `125` semantics.

### Fixed

- Replace quadratic sensitive-assignment rescanning with a bounded forward scan so one long ordinary diagnostic token cannot cause disproportionate log-processing work.
- Avoid process-wide file-size limits that would incorrectly constrain coverage databases, compiled assets, archives, and other legitimate repository artifacts unrelated to stdout/stderr evidence.

### Documentation

- Add APA 7 doctoring for the sandbox command/output redaction boundary, structured diagnostics, availability controls, verification evidence, limitations, and rollback requirements.
- Add APA 7 doctoring for bounded subprocess pipe draining, process-group termination, bounded service evidence, exit-code precedence, realistic flood tests, limitations, and rollback requirements.
