# Trusted `uv.lock` materialization: evidence and design record

## Decision

Central coverage automation may translate a tracked `uv.lock` from the exact
validated pull-request base revision into a pip-compatible, hash-pinned
requirements closure. The translation must not depend on a mutable runner tool,
repository-head dependency metadata, or network access during export.

The implementation therefore:

1. reads `uv.lock` and its sibling `pyproject.toml` only through `git show` at a
   validated 40-character commit SHA;
2. downloads one fixed official Astral `uv` archive from a literal HTTPS URL;
3. verifies the bounded archive with a pinned SHA-256 digest before extraction;
4. accepts only the expected regular-file tar member within explicit size bounds;
5. verifies the installed executable reports the exact pinned `uv` version;
6. executes `uv export` with `--frozen`, `--offline`, `--no-emit-project`, and
   `--no-editable` in an isolated temporary project;
7. rejects every nonempty export unless every logical requirement carries an
   explicit `--hash=` value; and
8. exposes only generated requirements files and a source manifest to the later
   networkless coverage environment.

## Standards and current-tool rationale

The approved SLSA specification is version 1.2. Its provenance model treats
verifiable origin and production history as software-supply-chain evidence, and
its source track distinguishes trusted robots whose identity and codebase cannot
be unilaterally influenced. Binding reads to an immutable Git revision, pinning
the exporter artifact by digest, and rejecting malformed exporter output follow
that trust-minimization direction without claiming a SLSA conformance level.

Astral documents `uv export` as the supported conversion path from `uv.lock` to a
pip-compatible requirements format. The command is invoked with `--frozen` so it
cannot update the lock and `--offline` so the conversion cannot access the
network. Project and editable entries are omitted because the coverage sandbox
loads repository source directly and needs only the third-party dependency
closure.

Generic requirements discovery continues to accept a global
`--require-hashes` directive because pip performs a later closure preflight.
Trusted `uv export` output uses a stricter rule: each emitted requirement must
carry its own hash. This prevents a successful but malformed exporter result
such as `--require-hashes` followed by an unhashed requirement from entering the
trusted build context.

## Verification contract

Regression coverage must prove:

- base-revision-only reads and rejection of unsafe revision/path shapes;
- fixed-origin download, redirect rejection, bounded reads, archive digest,
  member type, member size, executable size, and exact executable version;
- frozen and offline exporter arguments;
- timeout, process, parse, and exporter failures fail closed;
- orphan locks and empty third-party closures remain nonfatal and explicit;
- every nonempty emitted requirement includes a hash; and
- the changed production module retains 100% statement and branch coverage and
  100% production docstrings.

## References

Astral Software, Inc. (n.d.). *Exporting a lockfile*. uv documentation. Retrieved
August 4, 2026, from https://docs.astral.sh/uv/concepts/projects/export/

Astral Software, Inc. (n.d.). *Locking and syncing*. uv documentation. Retrieved
August 4, 2026, from https://docs.astral.sh/uv/concepts/projects/sync/

Supply-chain Levels for Software Artifacts. (2026). *SLSA specification
(version 1.2)*. https://slsa.dev/spec/v1.2/

Supply-chain Levels for Software Artifacts. (2026). *Provenance (version 1.2)*.
https://slsa.dev/spec/v1.2/provenance

Supply-chain Levels for Software Artifacts. (2026). *Source: Requirements for
producing source (version 1.2)*. https://slsa.dev/spec/v1.2/source-requirements
