# Changelog

All notable changes to the ContextualWisdomLab central GitHub control plane are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versioned releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Keep the native Atheris fuzz-engine lock in dedicated repository fuzz workflows instead of installing it in the generic OpenCode coverage image; immutable hash-pinned property and regression test locks remain eligible for central coverage materialization.

### Documentation

- Add an APA 7 doctoring record for the generic coverage/native fuzz-engine dependency boundary, exact-base trust model, verification fixture, limitations, and rollback requirements.
