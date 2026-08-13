# Trusted requirements-directory lock discovery

## Decision

The central OpenCode coverage image materializes dependency closures only from
regular files in the authenticated pull-request base commit. In addition to the
conventional `requirements*.txt` and `requirements.lock` names, it recognizes a
`.txt` file that is a **direct child** of a directory named `requirements`, such
as `requirements/ci.txt` or `services/scoring_service/requirements/package.txt`.

The path rule grants candidate status only. A global `--require-hashes`
directive is not trust evidence by itself. Every non-directive logical line must
be either:

- an exact package `==` requirement with one or more complete 64-hex SHA-256
  `--hash=` values; or
- a two-token `-r` / `--requirement` include naming a bounded relative
  candidate lock path (`requirements*.txt`, `requirements.lock`, or a
  direct `.txt` child of a `requirements/` directory).

The include grammar rejects absolute paths, `..` traversal, URL/scheme syntax,
query or fragment syntax, shell-home expansion, Windows-style separators,
option-like targets, and additional inline options or hashes. Package lines
using ranges such as `>=`, truncated/non-SHA-256-looking hash values, index or
other option lines, local/direct references, and other syntax that merely
contains a `--hash=` substring do not gain trusted candidate status.

This parser is a **pre-materialization eligibility boundary**, not a dependency
solver. The exact trusted source path is recorded in the manifest and the
existing installer separately preflights every candidate as an independently
installable `pip --require-hashes` closure. That second proof remains mandatory:
pip's hash-checking mode intentionally fails when a requirement participating in
the installation is not fully hashed. Syntax qualification therefore cannot
substitute for dependency-closure proof.

CWE-494 forbids downloading source or an executable from a remote location
without verifying origin and integrity (MITRE, 2026). A global
`--require-hashes` directive therefore cannot promote an unpinned or
range-pinned line into the networked coverage image.

Unpinned notes, directive-only files, input files, deeper descendants, symbolic
links, pull-request-only files, malformed Git tree entries, and unsafe include
syntax remain excluded from the networked coverage image.

## Operational reason

Concrete environment locks are frequently organized below a `requirements`
directory and use role names such as `ci.txt` or `package.txt`. Ignoring those
safe base-owned locks leaves isolated coverage without runtime dependencies even
when the repository maintains a complete generated closure. The resulting import
failure measures the coverage image rather than the changed production code.

Conversely, treating the presence of the substring `--hash=` as trust evidence
would let a range requirement, malformed digest, pip option, or path/URL include
cross the materialization boundary. The accepted design therefore combines
base-commit provenance, a narrow grammar, and an independent pip closure
preflight rather than relying on file names or hash-looking text alone.

## Verification

- A failing contract first proved that `requirements/ci.txt` was undiscoverable.
- A later RED security contract proved that range requirements, malformed
  digests, pip option lines, absolute/traversing includes, and includes carrying
  extra inline options could be materialized by the earlier substring test.
- Direct `requirements/*.txt` and nested-service equivalents remain eligible.
- A deeper `requirements/nested/ci.txt` path and unrelated `docs/ci.txt` remain
  ineligible.
- Exact `==` package pins with complete SHA-256 hashes are accepted; `>=` and
  malformed/truncated hash forms are rejected.
- Bounded relative includes such as `--requirement requirements-other.txt` and
  `-r requirements/other.txt` are accepted. Current-directory prefixes
  (`./requirements/other.txt`), empty path components (`requirements//other.txt`),
  URL, absolute, traversal, home-expansion, query/fragment, backslash, and
  option-like forms are rejected.
- A global `--require-hashes` directive combined with an unpinned requirement is
  rejected rather than promoted into the networked coverage image.
- Only qualifying base-owned candidates are emitted from realistic temporary Git
  bases; unpinned `.in`, note, and hostile direct-child files remain absent.
- Exact-head Python 3.14 quality requires the focused suite, complete central
  suite, 100% production statement and branch coverage, 100% public docstrings,
  compilation, and security/supply-chain workflows. Python 3.10 compatibility
  remains a separate minimum-runtime contract.

## References

MITRE. (2026). *CWE-494: Download of code without integrity check*.
https://cwe.mitre.org/data/definitions/494.html

Python Packaging Authority. (2026). *Install requires vs requirements files*.
Python Packaging User Guide. Retrieved August 10, 2026, from
https://packaging.python.org/en/latest/discussions/install-requires-vs-requirements/

Python Packaging Authority. (2026). *Repeatable installs*. pip documentation.
Retrieved August 10, 2026, from
https://pip.pypa.io/en/latest/topics/repeatable-installs/

Python Packaging Authority. (2026). *Requirements file format*. pip
26.1.2 documentation. Retrieved August 10, 2026, from
https://pip.pypa.io/en/stable/reference/requirements-file-format/

Python Packaging Authority. (2026). *Secure installs*. pip 26.1.2
documentation. Retrieved August 10, 2026, from
https://pip.pypa.io/en/stable/topics/secure-installs/
