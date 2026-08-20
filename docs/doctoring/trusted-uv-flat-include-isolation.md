# Trusted uv flat-include isolation

## Status

Accepted on 2026-08-18 for generated base Python lock publication.

## Buyer-facing failure

The central coverage lane renames every selected source lock to a generated flat
name such as `requirements-000.txt`. A source requirements file containing a
relative `-r` or `--requirement` directive is valid pip syntax, but pip resolves
the referenced path relative to the generated output location. Publishing only
the referrer can therefore fail a downstream repository before its own tests,
branch coverage, or docstring evidence executes.

## Root cause and decision

The previous implementation conflated two authority boundaries:

- `_is_hash_pinned` answers whether a source file uses bounded requirements
  syntax, including a normalized relative include; and
- `base_hash_locks` decides whether one source blob can be copied independently
  under a generated flat name.

A bounded relative include may pass the first question while failing the second.
The materializer now keeps bounded-include syntax diagnostics unchanged but uses
`_is_flat_materializable_lock` for publication. That predicate admits only a
non-empty, standalone closure whose logical requirement lines are exact `==`
pins carrying complete SHA-256 hashes. `base_hash_locks` also uses the existing
path-aware candidate predicate, so independently complete direct `.txt` children
such as `requirements/ci.txt` and `service/requirements/package.txt` remain
eligible.

## Security and ownership boundary

No URL, proxy, redirect, package index, caller-controlled header, output path,
review authority, credential, or repository write scope is expanded. The fixed
GitHub Releases uv download and redirect boundary is unchanged. Relative include
publication remains fail-closed until a separately reviewed implementation can
reconstruct the complete immutable include graph, preserve source-directory
identity, rewrite every edge, and prove the resulting closure.

This is a central `.github` materialization correction. Product repositories,
including BandScope, retain ownership of their own requirements, tests, and
runtime behavior. The central workflow must not edit a downstream product merely
to work around a generated-path defect.

## Verification and operator action

The regression suite proves all of the following:

1. both `-r` and `--requirement` referrers are excluded from flat publication;
2. an independently complete referenced lock remains eligible;
3. complete direct `.txt` children of a directory named `requirements` are
   discovered; and
4. empty, directive-only, standalone exact-pin, and include-only inputs exercise
   both branches of the publication predicate.

Merge requires the focused trusted-uv suite, complete central tests, production
statement and branch coverage at 100%, complete production docstrings, Python
3.10 and current-stable compilation, exact-head security checks, and ordinary
protected-branch review. A downstream repository using nested requirements
should publish one standalone hash-locked closure or wait for a graph-aware
materializer; operators must not manually copy or rename an unresolved include.

## Rollback

Do not restore relative include publication. A rollback would reintroduce a
source-relative edge into a namespace that no longer preserves source location.
Restore only after a graph-aware implementation has equivalent RED fixtures,
immutable edge rewriting, closure verification, and the same security gates.

## APA 7th references

Python Packaging Authority. (2026). *Requirements file format*. pip
documentation. https://pip.pypa.io/en/stable/reference/requirements-file-format/

Python Packaging Authority. (2026). *Secure installs*. pip documentation.
https://pip.pypa.io/en/stable/topics/secure-installs/
