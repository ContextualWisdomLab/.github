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
3. installs one process-wide urllib opener with an empty proxy map and a redirect
   handler that rejects every redirect before urllib creates a target request;
4. downloads one fixed official Astral `uv` archive from a literal HTTPS URL and
   accepts a response only when its parsed origin remains HTTPS,
   `releases.astral.sh`, and the absent or explicit default port 443; malformed
   or nondefault ports fail closed;
5. verifies the bounded archive with a pinned SHA-256 digest before extraction;
6. accepts only the expected regular-file tar member within explicit size bounds;
7. writes the executable with mode `0755` and verifies that it reports the exact
   pinned `uv` version;
8. executes `uv export` with `--frozen`, `--offline`, `--no-cache`,
   `--no-progress`, `--color never`, `--no-emit-project`, and `--no-editable` in
   an isolated temporary project;
9. supplies a minimal environment with isolated home, temporary, cache, and
   configuration directories, disables dotenv loading and managed Python
   downloads, and does not inherit arbitrary runner variables;
10. keeps project metadata discovery enabled because the reconstructed
    `pyproject.toml` is an authoritative input; `--no-config` is deliberately not
    used because uv documents that it disables `pyproject.toml` discovery;
11. rejects every nonempty export unless every logical line is an exact normalized
    package `==` pin followed only by complete SHA-256 hashes; and
12. exposes only generated requirements files and a source manifest to the later
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

The download request uses neither ambient proxy configuration nor automatic
redirect following. Any HTTP redirect is rejected before a request to the target
location can be created. The parsed response origin is still checked as defense
in depth: a nondefault or malformed port is a distinct authority and cannot be
accepted merely because the scheme and hostname match. The archive bytes must
then match the pinned digest. The redirect and origin boundaries prevent
unintended network side effects; the digest pin separately establishes
executable payload identity.

Hash-pinned pip closures may also live as direct children of a directory
named `requirements`, such as `requirements/ci.txt`. File-name matching
alone misses those paths. `base_hash_locks` therefore uses
`_is_candidate_lock_path`, which treats a `.txt` child of a `requirements`
directory as eligible; content must still be a complete SHA-256 pin or a
bounded relative `-r` include before it enters the trusted image.

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
- the download opener is cached, disables ambient proxies, and rejects redirects
  before following them;
- fixed HTTPS scheme and hostname validation, acceptance only of an absent or
  explicit port 443, rejection of malformed and nondefault ports, bounded reads,
  archive digest, member type, member size, executable size, executable mode,
  and exact version;
- frozen, offline, cacheless, noninteractive exporter arguments;
- isolated environment directories and exclusion of arbitrary ambient variables;
- continued project metadata discovery with no `--no-config` regression;
- timeout, process, parse, and exporter failures fail closed;
- orphan locks and empty third-party closures remain nonfatal and explicit;
- every nonempty line is a normalized exact package pin with one or more complete
  SHA-256 hashes; and
- `pyproject.toml` enables branch measurement and the changed production module
  retains 100% statement and branch coverage plus 100% production docstrings.

## Exact-head quality evidence

GitHub documents that a workflow triggered by `pull_request` normally receives
`GITHUB_REF` as `refs/pull/<number>/merge` and `GITHUB_SHA` as the generated
merge revision. That behavior is useful for integration testing, but it cannot
support a claim that compatibility, coverage, docstrings, and compilation were
measured on the contributor's immutable head.

Both jobs in the dedicated trusted-uv quality workflow therefore pass
`github.event.pull_request.head.sha` explicitly to `actions/checkout`. The
workflow remains read-only and disables credential persistence. A permanent
contract requires the exact-head `ref` on both checkout steps, so a future edit
cannot silently convert exact-head evidence back into merge-preview evidence.
On a `push` event the pull-request field is absent; the checkout action receives
its documented empty default and continues to use the ref or SHA that triggered
the push.

## Repository-wide branch-coverage prerequisite repair

The exact pull-request merge tree exposed a broader central quality-contract
failure after the trusted uv slice itself had reached complete statement and
branch coverage. The complete repository suite passed all 850 tests, but the
shared OpenCode coverage command still exited nonzero because 52 defensive
branch arcs in unchanged central CI modules were not exercised. The measured
production result was 100% statements and 99% branches. Treating that outcome as
a uv exporter defect would have hidden the actual control-plane gap.

The repair does not narrow the production source set, omit unchanged modules,
lower `fail_under`, or add coverage pragmas. It adds deterministic regression
tests for the previously unexecuted scheduler, redaction, sandbox, JavaScript
coverage, R coverage, SBOM, approval, and evidence-contract branches. The
dedicated quality workflow now runs both the bounded trusted-uv slice and the
complete central test suite under branch measurement. This keeps the narrow
feature evidence useful while also proving the organization-wide 100% contract
that OpenCode enforces on the merge tree.

The repaired merge tree produced the following deterministic evidence:

- 883 tests passed;
- 6,573 of 6,573 production statements executed;
- 2,622 of 2,622 production branches executed;
- no missing production lines or partial branches; and
- every production module, class, and function in `scripts/ci` retained a
  docstring.

This prerequisite repair is intentionally test-only for production behavior. It
changes neither the trusted uv download boundary nor the dependency closure
accepted by the coverage sandbox.

## References

Astral Software, Inc. (n.d.). *Exporting a lockfile*. uv documentation. Retrieved
August 4, 2026, from https://docs.astral.sh/uv/concepts/projects/export/

Astral Software, Inc. (n.d.). *Locking and syncing*. uv documentation. Retrieved
August 4, 2026, from https://docs.astral.sh/uv/concepts/projects/sync/

Astral Software, Inc. (n.d.). *The uv command-line interface*. uv documentation.
Retrieved August 4, 2026, from https://docs.astral.sh/uv/reference/cli/

Berners-Lee, T., Fielding, R., & Masinter, L. (2005). *Uniform Resource Identifier
(URI): Generic syntax* (STD 66; RFC 3986). Internet Engineering Task Force.
https://doi.org/10.17487/RFC3986

GitHub. (n.d.). *actions/checkout*. GitHub. Retrieved August 5, 2026, from
https://github.com/actions/checkout

GitHub, Inc. (n.d.). *Events that trigger workflows*. GitHub Docs. Retrieved
August 5, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

Supply-chain Levels for Software Artifacts. (2025). *SLSA specification
(version 1.2)*. https://slsa.dev/spec/v1.2/

Supply-chain Levels for Software Artifacts. (2025). *Provenance (version 1.2)*.
https://slsa.dev/spec/v1.2/provenance

Supply-chain Levels for Software Artifacts. (2025). *Source: Requirements for
producing source (version 1.2)*.
https://slsa.dev/spec/v1.2/source-requirements
