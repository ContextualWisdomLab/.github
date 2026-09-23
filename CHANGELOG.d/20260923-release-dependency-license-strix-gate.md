### Central pre-publish dependency gate: parsed license denial, resolved-graph reconciliation, per-dependency Strix bindings

- `origin/main` had **no** fail-closed pre-publish dependency gate. The only license signal was
  `scripts/ci/sbom_inventory_aggregator.py`, a *scheduled, informational* org SBOM roll-up that
  flags GPL/AGPL/NOASSERTION for governance: it is not per-dependency, not fail-closed, and not
  bound to a release head. That gap blocked fast-mlsirm's 0.11.5 PyPI release and
  contextual-orchestrator's VCS-pin removal (#2342).
- New reusable `workflow_call` workflow `.github/workflows/release-dependency-license-strix-gate.yml`
  runs **before** a release workflow publishes. It has no `continue-on-error`, no `if: always()`,
  no neutral outcome, and no bypass; `permissions` is `contents: read` at both workflow and job
  scope, and every action is pinned to the same commits `exact-artifact-sbom-attestation.yml` uses.
  The decision code is materialized from `ContextualWisdomLab/.github` at `github.workflow_sha`
  into `trusted-gate/`, so a caller's tree can never supply it.
- New `scripts/ci/spdx_license_policy.py` is a recursive-descent SPDX 2.3 expression parser
  (`AND`/`OR`/`WITH`/parentheses/legacy `+`). Policy is applied to the parsed tree, never by
  substring matching: GPL, LGPL, and AGPL are denied in every version and in both the `-only` and
  `-or-later` spellings, an exception never rescues a denied base (`GPL-2.0-only WITH
  Classpath-exception-2.0` stays denied), and `missing`, `NOASSERTION`, `NONE`, `UNKNOWN`,
  `custom`, `LicenseRef-*`, and any unparseable expression fail closed. A dual-licensed dependency
  passes only when a non-denied operand is explicitly selected with a written rationale, which is
  copied into the artifact provenance as a CycloneDX component property. Bundled `LICENSE`,
  `COPYING`, and `NOTICE` text *is* substring-scanned — correct for prose — so metadata claiming
  MIT while shipping GPL text fails as a disagreement.
- New `scripts/ci/release_dependency_gate.py` enumerates both ecosystems and refuses any
  asymmetry: the hash-pinned Python lock against `pip inspect` of the build environment
  (`LOCK_ENV_MISMATCH`), and `Cargo.lock` against the full resolved build graph including
  build-dependencies and every `cfg()`-gated target (`CARGO_LOCK_GRAPH_MISMATCH`,
  `CARGO_CHECKSUM_MISSING`). It records name, version, source hash, license, license source, and
  distribution inclusion per dependency; verifies the captured source hash against the pin
  (`SOURCE_HASH_MISMATCH`); evaluates static and dynamic linking targets of shipped native
  libraries against an explicit, auditable platform-runtime soname allowlist (glibc, the GCC
  runtime-library-exception libraries, `libpython`) so a real compiled wheel can pass at all; and
  runs deterministic archive-escape and install-hook detectors (`ARCHIVE_PATH_ESCAPE`,
  `INSTALL_HOOK`).
- Strix evidence is accepted **only** as a machine-readable binding, one isolated synthetic
  fixture per dependency, simulating file parsing, install hooks, archive traversal, native library
  loading, credential/network attempts, and known-vulnerability surface. A textual "0 findings" or
  "No exploitable vulnerabilities detected" is rejected (`STRIX_TEXTUAL_PASS_REJECTED`), and a
  missing or malformed binding is a failure, never neutral (`STRIX_BINDING_MISSING`,
  `STRIX_BINDING_MALFORMED`, `STRIX_BINDING_UNBOUND`). The trusted binder is resolved next to the
  gate script's **own** directory, adopting `strix_quick_gate.sh`'s trusted-path semantics in new
  code without touching that file (PR #2291 owns its one-line repair).
- On success the gate seals exactly the six members
  `scripts/ci/verify_exact_artifact_sbom_handoff.py` expects — wheel, sdist, their CycloneDX 1.7
  SBOMs, `source-identity.json`, `checksums.sha256` — and emits all 17 inputs of
  `exact-artifact-sbom-attestation.yml` as workflow outputs, so provenance covers exactly the bytes
  that were gated. `tests/test_release_dependency_gate_capture_and_seal.py` proves the sealed
  directory is accepted verbatim by that verifier.
- Strix itself is invoked through the organization's existing trusted entry point
  `scripts/ci/strix_quick_gate.sh`, once per isolated fixture workspace via `STRIX_REPO_ROOT`,
  with `strix.yml`'s bootstrap invariants mirrored verbatim (private install umask,
  `--require-hashes --no-deps` against the unmodified `requirements-strix-ci-hashes.txt`, absolute
  non-symlinked executable inside the interpreter's scripts root, `chmod go-w`, digest pinned into
  `GITHUB_ENV`, sidecar-provided `LLM_API_KEY_FILE`/`LLM_API_BASE_FILE`/`STRIX_LLM_FILE`, and
  `orchestrator/free` as the only accepted model). The trusted binder is copied into each fixture
  workspace so the gate's binder lookup resolves both on current `main` and after #2291, without
  editing that file. `strix_runs/**/vulnerabilities.json` is normalized to an array only when it
  already is one (or carries a `vulnerabilities` array); any other shape writes no binding, so the
  gate refuses with `STRIX_BINDING_MISSING` rather than inventing a result.
- `scripts/ci/release_dependency_capture_raw.sh` runs the runner-only tools (`pip inspect`,
  `pip download`, `cargo metadata --locked`, `cargo fetch`, archive listing, `readelf -d`) and
  writes their output verbatim; every decision lives in the unit-tested Python that reads it. It
  inspects a `python3 -m venv --without-pip` environment holding exactly the lock, so the
  no-exemption lock/environment rule is not defeated by setup-python's preinstalled `pip`, and it
  fetches by exact pin with hash checking deliberately disabled so `SOURCE_HASH_MISMATCH` is
  observable rather than pre-empted by pip. The gate adds no Python dependency and does not touch
  any `anyio` pin or `requirements-strix-ci*` (#2278 owns that lane). Refs #2342.
