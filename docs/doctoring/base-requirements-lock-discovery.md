# Base requirements lock discovery contract

## Purpose

This doctoring record defines how the central review and coverage workflows discover hash-pinned Python requirement locks from an authenticated pull-request base commit. It records the nested-path regression repaired in pull request #939 and preserves the security boundary already developed in pull request #785.

## Incident

The materializer intentionally recognizes two candidate forms:

- conventional file names such as `requirements.txt`, `requirements-dev.txt`, and `requirements.lock`; and
- direct `.txt` children of any directory named `requirements`, such as `requirements/ci.txt` and `service/requirements/package.txt`.

The path predicate implemented both forms, but `base_hash_locks()` still called the basename-only predicate. As a result, a direct child such as `requirements/ci.txt` was rejected before its authenticated base blob and hash-pinned content could be evaluated. The implementation advertised path-aware eligibility while the collector enforced only legacy basename eligibility.

The repair changes the collector to call `_is_candidate_lock_path(candidate)` with the already parsed `PurePosixPath`. It does not broaden the accepted Git object types or relax content validation.

## Trust boundary

A candidate enters the generated build context only when every applicable condition holds:

1. The base revision is an exact 40-character hexadecimal commit SHA.
2. `git ls-tree` reports a regular `100...` blob in that exact base tree.
3. The repository-relative path is non-absolute and contains no `..` component.
4. The path is either a conventional requirements lock name or a direct `.txt` child of a directory named `requirements`.
5. Every substantive requirement is an exact `==` pin with complete SHA-256 hashes, or a separately bounded relative requirements include.
6. Symlinks, gitlinks, malformed tree entries, unpinned files, unsafe includes, and pull-request-only content remain excluded.
7. `uv.lock` follows its separate trusted export path and still requires the corresponding base-owned `pyproject.toml`.

Path eligibility is candidate discovery, not dependency trust. The existing hash, include, export, and downstream closure checks remain authoritative.

## Test-first evidence

Temporary repair workflow run `31787913977` executed the following sequence on head `912313ff92cdcee6f240e9584f79ca37615ee5a2`:

1. Created a temporary Git repository containing hash-pinned `requirements/ci.txt` and `service/requirements/package.txt` blobs.
2. Confirmed the regression test failed before the implementation change because neither path was collected.
3. Replaced the basename-only collector predicate with the repository-relative path predicate.
4. Confirmed both paths were returned in deterministic repository order.
5. Compiled the implementation and regression test and ran `git diff --check`.
6. Deleted the temporary writer workflow before committing the production change.

An earlier repair attempt failed before exercising the assertion because direct script execution omitted the repository root from `sys.path`. The corrected workflow ran both RED and GREEN phases with the same explicit `PYTHONPATH=.` environment, so the observed transition is attributable to the collector change rather than import setup.

## Permanent regression command

```bash
PYTHONPATH=. python3 tests/test_materialize_base_python_requirement_paths.py
python3 -m compileall -q \
  scripts/ci/materialize_base_python_requirements.py \
  tests/test_materialize_base_python_requirement_paths.py
git diff --check
```

The repository quality workflow must also run the full materializer and Strix regression suites on the exact pull-request head. Focused repair evidence cannot replace protected-branch checks, semantic review, or required independent approvals.

## Change-management rule

Future changes to candidate naming, path parsing, Git tree filtering, requirement includes, `uv.lock` export, or materialized manifests must update the path-discovery tests and the broader materializer suite together. A path predicate and its collector call site must not evolve independently.
