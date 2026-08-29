# OpenCode coverage validated-head Python locks

검토 기준일: **2026-08-29**

## Decision

OpenCode coverage may use a pull request's changed Python requirements lock when
the lock is read from the authenticated, validated HEAD SHA and every logical
requirement is an exact `==` pin with one or more complete SHA-256 hashes. A
changed HEAD lock must be flat: URLs, VCS sources, relative includes, and
unpinned lines do not cross into the networked coverage-image build context.

An unchanged lock remains materialized from the validated base SHA. When a
tracked base lock changes, the validated flat HEAD lock replaces it rather than
installing both revisions. For an unchanged base lock with a bounded relative
include, the include blob is compared with the exact HEAD tree: a changed
include is materialized only when it remains flat and fully SHA-256 pinned, while
deleted or invalid content fails closed. A base lock that becomes unbounded
fails closed. A changed or newly added `uv.lock` project with a regular sibling
`pyproject.toml` is re-exported from the exact HEAD through the existing frozen,
offline, checksum-validating exporter; deleted projects remove their base
registry and VCS inputs, and unchanged projects remain base-bound. Base and HEAD
`uv.lock` inventories are completed before export, so a changed or deleted HEAD
project never requires its stale base export to succeed first.

The workflow keeps this materialization enabled for every tracked `.txt` change:
the path alone cannot prove that a file is not a bounded include target. Content
validation still decides whether that candidate can enter the trusted image.

## Root cause

The coverage image was built only from `PR_BASE_SHA` Python locks. A legitimate
dependency pull request could therefore add a platform wheel hash to its
current-head lock, while the image builder still saw the older base file. Pip
then failed before PR tests because the compatible wheel's hash was absent from
the stale lock. The JavaScript materializer already handled this case by
validating and recording changed HEAD locks; Python had no equivalent path.

## Security boundary

The central workflow and materializer validate the exact base and head revisions
before any Git tree read. Only a regular candidate lock from the exact HEAD is
read, and only a flat SHA-256-pinned file can replace a base lock. Changed
`uv.lock` projects reuse the same isolated exporter against exact HEAD
`uv.lock` and sibling metadata, then apply the established registry hash and
organization-owned full-commit VCS validation. A bounded
include beneath an unchanged base lock is likewise read from HEAD only after
its exact base/head blob comparison and regular-file check; its content must be
flat and fully pinned. The image installer retains
`pip install --require-hashes --only-binary=:all:`; source distributions, build
backends, VCS dependencies, unbounded requirements, deleted includes, and
invalid include content remain rejected or outside this path. The later PR
sandbox remains networkless and credential-free.

This is a provenance and compatibility repair, not an approval or merge
mechanism. Current-head OpenCode, Strix, other required Checks, review threads,
and protected-branch rules remain independent gates.

## Verification contract

Regression coverage proves that a changed exact-head lock replaces stale base
content; a changed, deleted, or invalid include beneath an unchanged parent is
handled from the exact HEAD; and changed, deleted, registry-only, VCS-only, and
mixed `uv.lock` projects replace or remove every base export component before
image build. Workflow contract coverage proves that the materializer receives
both `PR_BASE_SHA` and `PR_HEAD_SHA`. The central quality gate must retain
complete statement, branch, and docstring coverage.

## APA 7th references

Python Packaging Authority. (n.d.). *Secure installs*. pip documentation.
Retrieved August 29, 2026, from
https://pip.pypa.io/en/stable/topics/secure-installs/

Python Packaging Authority. (n.d.). *pip install*. pip documentation. Retrieved
August 29, 2026, from https://pip.pypa.io/en/stable/cli/pip_install/

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification (version
1.2)*. https://slsa.dev/spec/v1.2/
