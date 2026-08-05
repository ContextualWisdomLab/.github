# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Upgrade the central Strix dependency snapshots to `aiohttp==3.14.3`, `cryptography==50.0.0`, and the compatible `pyOpenSSL==26.4.0` closure so the hard dependency gates contain no known affected releases.
- Redact credentials from every sandbox evidence publication sink, including completed and timed-out process output, service log tails, commands, reviewer notes, nested JSON values, and JSON object keys.

### Fixed

- Replace quadratic sensitive-assignment rescanning with a bounded forward scan so one long ordinary diagnostic token cannot cause disproportionate log-processing work.

### Documentation

- Add an APA 7 doctoring record for the sandbox command/output redaction boundary, structured diagnostics, availability controls, verification evidence, limitations, and rollback requirements.
