# Trusted requirements-directory lock discovery

## Decision

The central OpenCode coverage image materializes dependency closures only from
regular files in the authenticated pull-request base commit. In addition to the
conventional `requirements*.txt` and `requirements.lock` names, it recognizes a
`.txt` file that is a **direct child** of a directory named `requirements`, such
as `requirements/ci.txt` or `services/scoring_service/requirements/package.txt`.

The path rule grants candidate status only. The existing content boundary still
requires nonempty hash-pinned logical requirements, records the exact trusted
source path in the manifest, and preflights each candidate as an independently
installable `pip --require-hashes` closure. Unpinned notes, input files, nested
descendants, symbolic links, pull-request-only files, and malformed Git tree
entries remain excluded.

## Operational reason

Concrete environment locks are frequently organized below a `requirements`
directory and use role names such as `ci.txt` or `package.txt`. Ignoring those
safe base-owned locks leaves isolated coverage without runtime dependencies even
when the repository maintains a complete generated closure. The resulting import
failure measures the coverage image rather than the changed production code.

## Verification

- A failing contract first proved that `requirements/ci.txt` was undiscoverable.
- Direct `requirements/*.txt` and nested-service equivalents are accepted.
- A deeper `requirements/nested/ci.txt` path and unrelated `docs/ci.txt` remain
  ineligible.
- Only the hash-pinned candidate is emitted from a realistic temporary Git base;
  unpinned `.in` and human-readable `.txt` files remain absent.
- The focused materializer suite, complete central suite, statement and branch
  coverage, docstring gate, compilation, and exact-head security workflows are
  required before merge.

## References

Python Packaging Authority. (2026). *Install requires vs requirements files*.
Python Packaging User Guide.
https://packaging.python.org/en/latest/discussions/install-requires-vs-requirements/

Python Packaging Authority. (2026). *Repeatable installs*. pip documentation.
https://pip.pypa.io/en/stable/topics/repeatable-installs/

Python Packaging Authority. (2026). *Requirements file format*. pip
documentation.
https://pip.pypa.io/en/stable/reference/requirements-file-format/
