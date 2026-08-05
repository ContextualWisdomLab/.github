# Coverage Native-Fuzz Lock Boundary Design

## Status

Approved for autonomous implementation under issue #762.

## Problem

The central trusted-base dependency materializer currently treats every hash-pinned `requirements*.txt` file as part of the generic offline coverage image. That is too broad: native coverage-guided fuzz engines are execution toolchains for dedicated fuzz jobs, not import dependencies for ordinary statement/branch coverage. Selecting `requirements-atheris.txt` can make a coverage review fail on an interpreter-specific native wheel before any selected application or test code runs.

## Decision

Classify exact native fuzz-engine lock names as coverage-incompatible. The first supported name is `requirements-atheris.txt`.

The classification is path-independent so standalone repositories and nested MSA modules receive the same treatment. Hash-pinned property/unit-test locks such as `requirements-property.txt` remain eligible. Exact-base Git reads, immutable-source selection, hash requirements, bounded output, and deterministic ordering remain unchanged.

## Components

### Lock-role classifier

A pure helper receives one file name and returns whether it represents a native fuzz runtime. The helper uses an immutable exact-name set rather than substring matching, which avoids excluding unrelated dependencies such as `requirements-fuzz-regression.txt`.

### Materializer integration

`base_hash_locks` checks the role before reading or exporting the blob. Excluded native fuzz locks never enter the Docker build context or trusted coverage image. Dedicated repository fuzz workflows continue installing those locks directly.

### Verification

A real temporary Git repository proves that:

- `fuzz/requirements-atheris.txt` is excluded;
- `fuzz/requirements-property.txt` remains materialized;
- a similarly named non-exact lock remains eligible;
- existing exact-base, hash, symlink, malformed-tree, uv, and CLI contracts remain green;
- changed production helpers retain 100% statement/branch coverage and docstrings.

## Security boundary

The change reduces trusted coverage-image inputs; it does not accept PR-controlled dependency metadata or weaken `--require-hashes`. Exclusion is limited to a toolchain that the generic coverage job never executes. Adding another excluded name requires a separate reviewed change, evidence, and test.

## Non-goals

- changing the dedicated Fuzz required workflow;
- changing OpenCode/Noema/Strix models or credentials;
- changing NVIDIA NIM keys;
- suppressing coverage failures in selected application/test dependencies;
- interpreting arbitrary requirement contents or comments as trusted role metadata.
