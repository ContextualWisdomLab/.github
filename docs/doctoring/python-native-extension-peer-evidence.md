# Doctoring record: Python native-extension peer evidence

## Purpose

The central OpenCode coverage sandbox executes pull-request tests without a
repository credential, package-index access, or permission to run
pull-request-selected build/install hooks. That isolation is intentional, but a
mixed Rust/Python project can require a compiled PyO3 extension during pytest
collection. A plain source checkout then raises `ModuleNotFoundError` before any
Python test is collected even when the exact pull-request head has already built,
installed, and tested the extension in trusted repository jobs.

This record defines a bounded classifier and exact-head peer-evidence gate. The
classifier does **not** convert a missing extension into passing test evidence.
It can only identify one narrow execution-environment limitation and defer the
final decision to separately successful native build and test checks on the same
commit.

CWE-829 forbids including functionality from an untrusted control sphere
(MITRE, 2026). A source-only sandbox therefore must not run pull-request
maturin or cargo hooks to recover from `ModuleNotFoundError`. Peer evidence
is exact-head repository CI, not a sandbox compile.

## Observed failure

`ContextualWisdomLab/fast-mlsirm#546` uses the maturin mixed-project layout:

```toml
[build-system]
build-backend = "maturin"

[tool.maturin]
bindings = "pyo3"
manifest-path = "crates/fast-mlsirm-py/Cargo.toml"
module-name = "fast_mlsirm._core"
python-source = "python"
```

The repository CI first builds and installs the native module and then runs
pytest. The isolated central source sandbox deliberately does not perform that
build, so collection stops at:

```text
ModuleNotFoundError: No module named 'fast_mlsirm._core'
```

Maturin documents that `module-name` places the compiled extension inside the
configured Python source tree and that `maturin develop` or an installation step
materializes the shared library. PyO3 likewise documents that a native module
must be compiled and exposed with the matching module name before Python can
import it. The source checkout alone is therefore not equivalent to the
installed package.

## Classification contract

`scripts/ci/python_native_extension_peer_gate.py classify-pytest` accepts a
failure only when every condition below is true:

1. `pyproject.toml` is a bounded, regular, non-symlink UTF-8 file.
   The workflow reads those bytes from the exact pull-request head's immutable
   Git blob and passes the separately validated repository-relative
   `pyproject.toml` location as logical path data; a temporary snapshot path
   never becomes repository identity.
2. The build backend is exactly `maturin` and bindings are exactly `pyo3`.
3. `module-name`, `manifest-path`, and `python-source` are safe relative values.
4. The pytest log is bounded, complete, and contains only collection errors.
5. Every terminal exception is `ModuleNotFoundError` for the declared module.
6. Every collection-error block contains a direct import of that module.
7. The interruption count, collection-block count, and missing-module count
   agree exactly.
8. There is no failure, setup/teardown error, internal pytest error, crash,
   segmentation fault, or truncation marker.
9. The changed-file list is bounded, unique, and traversal-free.
10. The pull request does not change Rust source, Cargo metadata, native stubs,
    maturin metadata, dependency locks, requirements, packaging files, GitHub
    workflows/actions, or any file under the native crate directory.

A rejected classification remains an ordinary blocking test failure.

## Exact-head peer evidence

A successful classification is not approval. Before the central workflow may
accept it, `require-checks` must receive normalized `CheckRun` records for the
exact 40-character pull-request head and prove all trusted requirements. The
initial `fast-mlsirm` contract requires:

```text
CI::python
CI::rust
CI::package
```

Every matching check must be a GitHub `CheckRun`, belong to the trusted workflow,
carry the exact head SHA, have status `COMPLETED`, and conclusion `SUCCESS`.
Missing, pending, failed, cancelled, neutral, skipped-required, stale-head,
status-only, or lookalike check records fail closed. The workflow and check names
must be supplied by trusted central or protected-base configuration, not by pull
request prose.

GPU and fuzz evidence remain independent repository gates. The peer gate neither
removes nor reinterprets them.

## Change-sensitive boundary

The deferral exists only for an unchanged native/package trust boundary. Any
change to the extension implementation, Cargo manifests or lock, maturin
configuration, native stub, packaging metadata, dependency locks (including
`.in` / `.txt` / `.lock` files under a `requirements` path), or CI workflow
requires a direct trusted native build path. A prose file such as
`docs/requirements/overview.md` is not a lock. This prevents a pull request from
changing the thing being imported while asking the central sandbox to trust an
older binary or a weakly named passing check.

Python business or reporting code and its tests may use the deferral when the
native boundary is unchanged, but the current-head repository Python job must
still execute the complete suite against the built extension.

## Security and privacy boundary

The helper reads only bounded regular files and performs no network access,
subprocess execution, package installation, token access, or mutation. It does
not load the target project as Python code. TOML and JSON are parsed as data.
Repository paths reject absolute paths, parent traversal, current-directory
aliases, Windows separators, NUL, and duplicates.

Untrusted pytest executes only after the metadata snapshot is sealed. The
classifier therefore reads maturin configuration from that immutable copy and
derives change-boundary paths from a distinct, traversal-free logical path
anchored to the validated coverage repository. It never resolves the temporary
snapshot as though it lived inside the repository and never rereads mutable
post-test project metadata.

The classifier does not make arbitrary `ModuleNotFoundError` safe. Missing
third-party dependencies, syntax/import defects in Python modules, mixed
exceptions, runtime crashes, and ordinary test failures remain blocking.

## Testing evidence

The focused suite includes the exact `fast_mlsirm._core` collection shape plus
adversarial cases for:

- wrong and mixed missing modules;
- inconsistent collection counts;
- failed tests and setup/teardown errors;
- internal pytest errors, crashes, and truncated output;
- malformed TOML and unsafe paths;
- changed Rust, Cargo, packaging, dependency, workflow, and native-stub inputs;
- stale, pending, failed, status-only, wrong-workflow, and misleading checks;
- malformed SHAs, duplicate requirements, unsafe JSON, and missing files;
- flat and GraphQL-shaped workflow metadata;
- both CLI success and fail-closed paths;
- the exact embedded workflow command with an outside-repository sealed
  snapshot plus a canonical logical `pyproject.toml` path.

Exact-head verification reported 115 focused tests passing with 272/272
production statements and 122/122 production branches covered.
Permanent central quality and security workflows remain authoritative after the
branch is pushed.

## Interpretation limits

This gate establishes neither product correctness nor scientific validity. It
only prevents a known source-only sandbox limitation from being confused with a
Python defect while preserving exact-head native evidence. Parameter recovery,
CPU/GPU parity, psychometric validity, fairness, and release readiness remain
separate product obligations.

## Rollback

Rollback removes the helper, tests, and workflow integration. The prior behavior
is fail-closed: any missing native module causes central coverage failure. No
rollback requires weakening branch protection, deleting repository tests, or
introducing a Python substitute for Rust arithmetic.

## References

GitHub. (2026). *REST API endpoints for workflow runs*. GitHub Docs.
https://docs.github.com/en/rest/actions/workflow-runs

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted control
sphere*. https://cwe.mitre.org/data/definitions/829.html

Maturin contributors. (2026). *Bindings*. Maturin user guide.
https://www.maturin.rs/bindings

Maturin contributors. (2026). *Configuration*. Maturin user guide.
https://www.maturin.rs/config

Maturin contributors. (2026). *Introduction: Mixed Rust/Python projects*.
Maturin user guide. https://www.maturin.rs/

Python Software Foundation. (2026). *The import system*. Python documentation.
https://docs.python.org/3/reference/import.html

PyO3 Project and Contributors. (2026). *Building and distribution*. PyO3 user
guide. https://pyo3.rs/main/building-and-distribution

PyO3 Project and Contributors. (2026). *Python modules*. PyO3 user guide.
https://pyo3.rs/main/module
