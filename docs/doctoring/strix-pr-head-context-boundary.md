# Strix PR-head dependency context boundary

Status: accepted 2026-08-21

## Incident

The Strix run for LineageWeave PR #192 materialized changed Python files but
not the unchanged local `backend/app` dependency package. The scanner then
reported `backend.app.post_eligibility` as missing even though that module was
present in the PR head and base repository. The same changed-file-only failure
mode affected `contextual-orchestrator` PR #801: `__main__.py` imported sibling
modules omitted from the temporary scan tree. Earlier attempts also encountered
NVIDIA NIM rate limits; those provider failures must remain visible and must not
be confused with a source finding.

TEPP PR #154 exposed the same completeness boundary for Rust: a workflow change
scoped the CI definition without the workspace's unchanged Cargo manifests,
toolchain selection, or cargo-deny policy.

## Decision

When a PR changes a Python module under `backend/app` or
`contextual_orchestrator`, the trusted Strix scope resolver enumerates every
Python file under that package from the exact PR head tree. It reads the Git
tree as NUL-delimited paths and applies the same
bounded path validator used for changed files, so ambiguous or unsafe entries
fail closed. The scope builder copies changed files from that head and
unchanged context from the trusted base checkout. The changed-file list
remains the finding-attribution boundary; this does not turn a context file
into a changed finding. The scan still executes only trusted scanner code and
treats PR-head blobs as non-executable data.

This is a product-neutral extension of the existing backend context contract;
it does not replace the repository-specific context list for other backend
layouts and does not downgrade provider or vulnerability failures.

## Evidence and rollback

The regression fixture creates changed modules that import unchanged siblings
in both packages, then asserts that the production scope contains the
dependencies and their trusted content. Roll back this change only with an
equivalent exact-head dependency-context contract;
removing the context or weakening the Strix gate is not an acceptable rollback.

For a workflow-scoped root Rust workspace, the behavioral fixture also requires
trusted `Cargo.toml`, `Cargo.lock`, `rust-toolchain.toml`, and `deny.toml`
contents in the materialized target. Rust source and Cargo manifests remain
governed changed inputs rather than context-only exemptions.

## References

National Institute of Standards and Technology. (2008). *Technical guide to
information security testing and assessment* (Special Publication 800-115).
https://doi.org/10.6028/NIST.SP.800-115

OWASP Foundation. (n.d.). *Web security testing guide*. Retrieved August 21,
2026, from https://owasp.org/www-project-web-security-testing-guide/
