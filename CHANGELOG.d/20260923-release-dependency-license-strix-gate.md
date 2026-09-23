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
- The gate now runs in **two stages**, so the licence determination precedes every credential and
  model step. `release_dependency_gate.py prescreen` (`stage: license`) enumerates the full
  dependency scope and applies the *same* `evaluate_dependency_license` decision the final gate
  uses, reading no Strix binding and requiring no provider credential: a GPL/LGPL/AGPL dependency,
  an `UNKNOWN`/missing licence, or an `OR` expression with no recorded permissive selection refuses
  the release before a secret is read. `capture` alone never rejected a licence — it only assembles
  evidence and fixtures — so making the secrets optional would not by itself have produced a
  pre-Strix rejection. The five provider secrets are therefore declared `required: false`, which is
  not leniency: `require-strix-credentials` refuses the Strix stage with `STRIX_CREDENTIALS_ABSENT`
  when any is absent, as a failing command rather than an `if:` condition, because a condition would
  *skip* the scan and let the release proceed unscanned. The reason code names only the absent
  variables and never echoes or measures a present value. Only a `full`-stage report may be sealed,
  so a passing prescreen can never stand in for the Strix stage.
- Dependency **scope is compared as a whole set**, per ecosystem, with `expected_count`,
  `enumerated_count`, `collected_count`, and `matched_count` recorded in the report and equality
  required. CO#1226 accepted coverage because one component of one ecosystem existed; an ecosystem
  this gate cannot enumerate is now `SCOPE_UNVERIFIABLE` rather than silently skipped, a collected
  set that is a subset of the producer's declared set is `SCOPE_SET_MISMATCH`, and so is capture
  material for something no declared ecosystem expects. Scope is direct, transitive, build, dev,
  optional and platform: `resolve_cargo_graph` walks every `resolve.nodes` edge regardless of
  `dep_kind` or target `cfg`, so a UEFI-only crate such as `r-efi` is an expected member and gets no
  target-based exemption.
- Licence metadata is read from **each fetched distribution's own** `METADATA`/`PKG-INFO`, by the
  trusted gate's `distribution-metadata`, which also re-checks that the archive declares the pinned
  project and version. It cannot come from `pip inspect` of the lock-only environment any more,
  because no such environment exists yet when the licence is judged; the enumeration is built from
  the same fetched set, in the `pip inspect` shape the lock/environment reconciliation already reads,
  so identity and licence stay consistent by construction and an entry that is not present exactly
  once is an error rather than a default. The previous metadata step ran `python3 -m pip show`
  without the `--python` target its neighbours carried, so it inspected the *runner's* global
  interpreter where the release dependencies are not installed at all.
- The exact release identity is shape-checked **first**. `workflow_call` can only type
  `source_sha` as `string`, and the gate's own 40-hex check was reached only after Strix had run, so
  `validate-inputs` now refuses a branch name or a short SHA before the release head is fetched.
- Failure evidence survives the failure that produced it: each report upload is bound to the step
  that writes it, running whether that step passed or failed but not when it never ran and not on
  cancellation. This is deliberately narrower than a blanket `always()`, and with
  `if-no-files-found: error` a report that should have been written but was not stays a failure
  instead of being masked. Neither upload can rescue the run. Refs #2342.
- **Install and capture now resolve from the same validated sources.** `pip install -r <lock>` reads
  the real lock and honors `--index-url`, `--extra-index-url` and `--find-links` in it, while the
  capture step's `pip download` used a reconstructed plain requirements file built with
  `grep -oE '^[A-Za-z0-9._-]+==[^ ;]+'`, which dropped every `-`-prefixed directive. Collection could
  therefore resolve from a different source than install, and any release lock using a private or
  extra index failed capture outright. The fix never forwards what the lock says: `lock-source-options`
  parses each directive, validates it, and only then emits an explicit option list, reusing the
  trusted-origin and bounded-path policy `materialize_base_python_requirements.py` already applies
  (HTTPS, default port, host allowlist, no userinfo; normalized relative path with no `.`/`..` and
  none of `\\ : ? #`). An unlisted origin is `LOCK_SOURCE_ORIGIN_DENIED`, a URL carrying userinfo is
  `LOCK_SOURCE_CREDENTIAL_IN_URL` and withholds the whole URL from both the message and the report, a
  path leaving the release tree is `LOCK_SOURCE_PATH_ESCAPE`, and a nested `-r`/`-c` include, an
  environment marker, or any other directive form is `LOCK_SOURCE_UNSUPPORTED`. Nothing is dropped
  silently, because silent dropping was the defect. The supported dialect is deliberately narrow and
  this organization's own `requirements-*-hashes.txt` files use none of these forms. The options are
  read into a bash array with the validator's exit status checked explicitly — *not* through
  `mapfile < <(…)`, where `set -e` discards a refusal and it would read as "no options" and resolve
  from the default index anyway. Source resolution decides only where pip looks: the hash pin still
  decides what is acceptable, so `SOURCE_HASH_MISMATCH` remains observable and an offline
  `--find-links` root cannot substitute different bytes. Refs #2342.
- **Nothing is installed before it has been adjudicated.** The gate's premise is that a denied,
  unknown or untrusted dependency is refused before any of it runs, but the workflow installed the
  whole release closure in a step that preceded *both* the lock-source validation and the licence
  prescreen. A GPL/LGPL/AGPL or `UNKNOWN` dependency therefore reached the environment first, and a
  lock pointing at an untrusted index had its directives honoured by that install while only the
  later capture validated them — so the first network action of the run was the unvalidated one. The
  order is now: validate the lock's sources (no network), collect the closure with
  `pip download --no-deps --only-binary=:all:` (wheels only, because `pip download` executes an
  sdist's build backend for metadata even with `--no-deps`), judge the licence, and only then
  install. The install is `--require-hashes --only-binary=:all: --no-index --find-links <collected>`
  over the very bytes that were inspected, so nothing is re-resolved or re-downloaded and the
  installed bytes are the judged bytes even where the lock records several hashes for one project —
  which a second hash-less download could not have established. `install-authorized` refuses the
  install unless a prescreen report records a passed `license` stage, so a missing, malformed or
  failing report fails closed instead of defaulting to permitted.
  One consequence is stated plainly rather than papered over: `LOCK_ENV_MISMATCH` is now evaluated
  against the *collected* closure, because no installed environment exists when the gate reads its
  capture. Agreement between that closure and the environment is enforced at install time instead,
  by pip itself: `--require-hashes` with `--no-index --find-links <collected>` can only install a
  file from the collected root that matches a hash the lock records, so a disagreement fails the
  install rather than being reported by a later inspect.
  `tests/test_release_dependency_install_ordering.py` pins the wiring rather than the parser: with
  `RELEASE_GATE_PIP` pointed at a recorder, a refused lock directive performs **no** pip call at all,
  an unauthorized licence stage performs **no** `install`, an authorized release performs exactly one
  offline hash-checked `install` from the collected root, and the workflow's step order is asserted
  because the defect lived there. Refs #2342.
- **Three release-blocking defects found by independent review of `03ba1777`, each with its own
  regression.** (1) *A permissive declaration was accepted as licence evidence.* The decision
  allowed the declared SPDX expression and then only looked for a **denied** title in the bundled
  text, so `scan_license_text` returning `None` was read as "the text is fine" — it only means no
  GPL/LGPL/AGPL title was found. Reproduced: MIT metadata with `license_texts = {}`, with
  `LICENSE = UNKNOWN`, and with `LICENSE = Commercial redistribution is prohibited.` each passed
  the licence stage with an empty failure list. `recognize_license_text` is the positive half —
  it returns the SPDX identifiers a body actually supports — so absent text is now
  `LICENSE_TEXT_MISSING`, an unrecognizable body is `LICENSE_TEXT_UNVERIFIED`, and a recognized
  body naming none of the declared identifiers is `LICENSE_TEXT_DISAGREEMENT`. Two of this
  repository's own fixtures were declaring one licence while bundling another and are corrected.
  (2) *The approval was not bound to what was installed.* `install_is_authorized` checked only
  `stage` and `result`, and the install re-read the original lock, so a two-field report authorized
  it and a lock recording several hashes for one project let `--require-hashes` accept an artifact
  whose licence and contents were never judged. The verdict now records `python_lock_sha256`, and
  `bind-install` refuses unless that lock still digests to what the verdict read, every judged
  artifact is present in the collected root **by digest**, and the root holds no other
  distribution; it then writes a requirements file pinning each project to the one judged digest,
  which is what the install reads. A swapped artifact, an extra unjudged wheel, an edited lock and
  a failing report each install nothing. (3) *The install could never run.* `python3 -m venv`
  symlinks `bin/python` on POSIX, and the interpreter guard refused symlinks outright, so a normal
  virtual environment exited 2 before pip was reached. The guard now resolves the link and requires
  the resolved target to be a regular executable file, which a real venv satisfies while a dangling
  link and a directory still fail. Refs #2342.
- **The gate's own toolchain is out of the prescreen's scope, and that limit is now written down
  instead of being implicit.** The same review noted that the pinned Strix toolchain
  (`requirements-strix-ci-hashes.txt`, materialized from `github.workflow_sha`) and the orchestrator
  sidecar's own lock are installed without passing through the licence stage. They are a different
  trust domain from the caller's release closure — pinned and reviewed in this repository — and the
  stage that judges the closure cannot judge the scanner it must run first without a cycle. The
  workflow says so at the install step: not an automatic exception for CI/build/dev dependencies,
  but a stated limit whose removal is an owner decision tracked separately. Nothing in this gate's
  output may be read as evidence that the gate's own dependencies were licence-judged. Refs #2342.

