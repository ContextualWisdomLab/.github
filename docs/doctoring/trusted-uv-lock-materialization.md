# Trusted `uv.lock` materialization: evidence and design record

## Decision

Central coverage automation may translate a tracked `uv.lock` from the exact
validated pull-request base revision into a pip-compatible, hash-pinned
requirements closure. The translation must not depend on a mutable runner tool,
repository-head dependency metadata, ambient runner configuration, or network
access during export.

The implementation therefore:

1. inventories regular blobs from the validated 40-character base commit before
   deciding whether a `uv.lock` has a sibling `pyproject.toml`;
2. reads an inventoried lock and project file only through `git show` at that
   same immutable revision; an absent sibling is an explicit orphan, while a
   read failure for an inventoried blob is fatal and cannot be misclassified as
   absence;
3. downloads one fixed official Astral `uv` archive from a literal HTTPS URL;
4. verifies the bounded archive with a pinned SHA-256 digest before extraction;
5. accepts only the expected regular-file tar member within explicit size bounds;
6. writes the executable with mode `0755` and verifies that it reports the exact
   pinned `uv` version;
7. executes `uv export` with `--frozen`, `--offline`, `--no-cache`,
   `--no-progress`, `--color never`, `--no-emit-project`, and `--no-editable` in
   an isolated temporary project;
8. supplies a minimal environment with isolated home, temporary, cache, and
   configuration directories, disables dotenv loading and managed Python
   downloads, and does not inherit arbitrary runner variables;
9. keeps project metadata discovery enabled because the reconstructed
   `pyproject.toml` is an authoritative input; `--no-config` is deliberately not
   used because uv documents that it disables `pyproject.toml` discovery;
10. rejects every nonempty export unless every logical line is an exact normalized
    package `==` pin followed only by complete SHA-256 hashes; and
11. exposes only generated requirements files and a source manifest to the later
    networkless coverage environment.

## Standards and current-tool rationale

The approved SLSA specification is version 1.2. Its provenance model treats
verifiable origin and production history as software-supply-chain evidence, and
its source track distinguishes trusted robots whose identity and codebase cannot
be unilaterally influenced. Binding reads to an immutable Git revision, pinning
the exporter artifact by digest, isolating ambient configuration, and rejecting
malformed exporter output follow that trust-minimization direction without
claiming a SLSA conformance level.

Astral documents `uv export` as the supported conversion path from `uv.lock` to a
pip-compatible requirements format. Hashes are emitted by default. `--frozen`
prevents lock mutation, `--offline` prevents network access, and `--no-cache`
uses an ephemeral cache. Project and editable entries are omitted because the
coverage sandbox loads repository source directly and needs only the
third-party dependency closure.

The global `--no-config` option is not appropriate here. uv documents that it
prevents discovery of both `pyproject.toml` and `uv.toml`. The materializer
instead isolates `HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, and `TMPDIR`,
sets `UV_NO_ENV_FILE=1` and `UV_PYTHON_DOWNLOADS=never`, and passes only a fixed
`PATH`. This preserves the exact reconstructed project metadata while excluding
user-level and runner-level configuration state.

Generic requirements discovery continues to accept a global
`--require-hashes` directive because pip performs a later closure preflight.
Trusted `uv export` output uses a stricter rule: every logical line must begin
with a normalized package name and exact `==` pin, and every following hash must
be a complete `sha256` digest. Option lines, direct or local references, other
algorithms, truncated digests, and global directives are rejected even when they
contain a `--hash=` substring.

The download response is required to remain on the HTTPS
`releases.astral.sh` host and the artifact bytes must match the pinned digest.
The digest is the executable payload identity; the host check prevents an
unreviewed cross-origin redirect from becoming the transport source.

## Modular and workspace boundary

Nested standalone services are supported: a repository may contain several
independent directories, each with its own sibling `pyproject.toml` and
`uv.lock`; each pair is read and exported independently from the immutable base
revision. This fits the organization’s standalone-product plus reusable-module
MSA contract without copying central review logic into product repositories.

A true uv workspace can require member `pyproject.toml` files in addition to the
root lock and root project metadata. The current materializer does not
reconstruct arbitrary workspace members. Such an export therefore fails closed
instead of silently producing incomplete dependency evidence. Workspace-member
reconstruction is tracked separately in `.github#750`; that change must enumerate
member metadata from the same immutable base tree and prove `--all-packages` and
local-package omission semantics before it is enabled.

## Verification contract

Regression coverage must prove:

- base-revision-only reads and rejection of unsafe revision/path shapes;
- an absent sibling project is skipped, but an inventoried project blob that
  cannot be read propagates a fatal error before uv starts;
- fixed-host download, cross-host redirect rejection, bounded reads, archive
  digest, member type, member size, executable size, executable mode, and exact
  version;
- frozen, offline, cacheless, noninteractive exporter arguments;
- isolated environment directories and exclusion of arbitrary ambient variables;
- continued project metadata discovery with no `--no-config` regression;
- timeout, process, parse, and exporter failures fail closed;
- orphan locks and empty third-party closures remain nonfatal and explicit;
- every nonempty line is a normalized exact package pin with one or more complete
  SHA-256 hashes; and
- the changed production module retains 100% statement and branch coverage and
  100% production docstrings.

## References

Astral Software, Inc. (n.d.). *Exporting a lockfile*. uv documentation. Retrieved
August 4, 2026, from https://docs.astral.sh/uv/concepts/projects/export/

Astral Software, Inc. (n.d.). *Locking and syncing*. uv documentation. Retrieved
August 4, 2026, from https://docs.astral.sh/uv/concepts/projects/sync/

Astral Software, Inc. (n.d.). *The uv command-line interface*. uv documentation.
Retrieved August 4, 2026, from https://docs.astral.sh/uv/reference/cli/

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification
(version 1.2)*. https://slsa.dev/spec/v1.2/

Supply-chain Levels for Software Artifacts. (2025). *Provenance (version 1.2)*.
https://slsa.dev/spec/v1.2/provenance

Supply-chain Levels for Software Artifacts. (2025). *Source: Requirements for
producing source (version 1.2)*.
https://slsa.dev/spec/v1.2/source-requirements
