# Trusted uv bounded-include materialization

## Status

Accepted on 2026-08-20 for generated base Python lock publication.

## Buyer-facing failure

The central coverage lane renames selected source locks to generated names such
as `requirements-000.txt`. A source requirements file containing a relative
`-r` or `--requirement` directive must keep that source-directory relationship;
publishing only the referrer can otherwise fail a downstream repository before
its own tests, branch coverage, or docstring evidence executes.

## Root cause and decision

The materializer separates two authority boundaries:

- `_is_hash_pinned` answers whether a source file uses bounded requirements
  syntax, including a normalized relative include; and
- `base_hash_locks` inventories those exact-base referrers and complete included
  blobs for graph-aware publication.

A bounded include is resolved relative to its exact base-tree parent, required to
be a regular blob containing only complete SHA-256 package pins, and written
under a preserved generated include directory. The root lock is rewritten to
that generated relative path. Missing targets, nested includes, unsafe path
components, and non-pinned leaves fail closed. Path-aware candidate discovery
continues to include direct `.txt` children such as `requirements/ci.txt` and
`service/requirements/package.txt`.

## Security and ownership boundary

No URL, proxy, redirect, package index, caller-controlled header, output path,
review authority, credential, or repository write scope is expanded. The fixed
GitHub Releases uv download and redirect boundary is unchanged. Include edges
are read only from the exact validated base revision, remain relative only inside
the generated include subtree, and are never followed beyond one direct
hash-pinned leaf.

This is a central `.github` materialization correction. Product repositories,
including BandScope, retain ownership of their own requirements, tests, and
runtime behavior. The central workflow must not edit a downstream product merely
to work around a generated-path defect.

## Verification and operator action

The regression suite proves all of the following:

1. both `-r` and `--requirement` referrers are rewritten to preserved generated
   include paths;
2. missing, unsafe, nested, or non-pinned included locks fail closed;
3. complete direct `.txt` children of a directory named `requirements` are
   discovered; and
4. empty, directive-only, standalone exact-pin, and bounded-include inputs
   exercise both branches of the publication predicate.

Merge requires the focused trusted-uv suite, complete central tests, production
statement and branch coverage at 100%, complete production docstrings, Python
3.10 and current-stable compilation, exact-head security checks, and ordinary
protected-branch review. A downstream repository using nested requirements
should keep each included leaf as an exact SHA-256-pinned regular base blob;
operators must not manually copy or rename an unresolved include.

## Rollback

Do not weaken the exact-base path, leaf-pin, or direct-include checks. Any future
rollback must retain equivalent missing-target, unsafe-path, nested-include, and
immutable edge-rewriting fixtures with the same security gates.

## APA 7th references

Python Packaging Authority. (2026). *Requirements file format*. pip
documentation. https://pip.pypa.io/en/stable/reference/requirements-file-format/

Python Packaging Authority. (2026). *Secure installs*. pip documentation.
https://pip.pypa.io/en/stable/topics/secure-installs/
