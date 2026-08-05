# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Upgrade the central Strix dependency closure to `aiohttp==3.14.3`, `cryptography==50.0.0`, and the compatible `pyOpenSSL==26.4.0` transitive release so the hard Python advisory gate no longer installs the affected prior versions.
- Add a permanent read-only exact-head closure contract that verifies the reviewed security floor and performs a real `--require-hashes` installation.

### Documentation

- Add APA 7 doctoring for the advisory evidence, generated-lock trust boundary, scope separation, verification requirements, and rollback prohibition.
