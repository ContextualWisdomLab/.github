# Negative-fixture verification plan for the central release dependency gate (#2342, #2347)

Prepared, **not approved to run**. No hosted run, publish, merge, approval or re-run is authorized
by this document. It closes the two written gaps the coordinator required alongside the reviewable
exact head, and it records one refutation the owner must decide on before any run is scheduled.

Central head this describes: `65727fa8411ec92672e03b1c6447b3a47d2616fc` on
`feat/release-dependency-license-strix-gate-2342`, on top of the reviewed
`3c3ca9b1445d4a73a9d47216ff88996f012f1757`.

Two claims are kept apart throughout, and must stay apart in any report that cites this file:

- **Reason codes verified locally.** Unit results from `pytest`, which prove a decision outcome and
  its reason code and nothing else.
- **Run-level facts.** "The Strix step did not start", "the gate job concluded `failure`", "the
  publish job did not start". None of these is established here. A failing unit-test wrapper is
  never a real release-gate failure, and a passing test is never a release PASS.

## Gap 1 — how a negative case enters the real gate

### The path, by step, subcommand and function

| # | Workflow step (`release-dependency-license-strix-gate.yml`) | Runs | Decides |
|---|---|---|---|
| 1 | `Validate the exact release identity before anything else runs` | `release_dependency_gate.py validate-inputs` | `validate_release_identity` — 40-hex `source_sha`, `owner/name` repository |
| 2 | `Install the release dependency closure into a lock-only environment` | `pip install --require-hashes --only-binary=:all: -r release-source/<python_lock_path>` into a `--without-pip` venv | — |
| 3 | `Download the exact distributions the caller intends to publish` | `actions/download-artifact` → `release-distributions/` | — |
| 4 | `Collect raw resolved-dependency evidence from both ecosystems` | `release_dependency_capture_raw.sh` | — (writes tool output verbatim; `capture_python` derives each `metadata.json` from `python/installed.json`) |
| 5 | `Assemble per-dependency evidence and isolated synthetic fixtures` | `release_dependency_gate.py capture` | `capture` → `build_evidence` → `evidence/<slug>.json`, `strix/fixtures/<slug>.json` |
| 6 | `Refuse a denied or unverifiable licence before any credential exists` | `release_dependency_gate.py prescreen` | **`gate(stage="license")` → `evaluate_dependency_license` → `declared_license_expression` → `spdx_license_policy.evaluate_license_expression`** |
| 7 | `Require every Strix provider credential before the Strix stage starts` | `release_dependency_gate.py require-strix-credentials` | `require_strix_credentials` → `STRIX_CREDENTIALS_ABSENT` |
| 8–11 | gateway, toolchain, credential binding, Strix | `strix_quick_gate.sh` per fixture workspace | — |
| 12 | `Refuse the release unless every dependency passes` | `release_dependency_gate.py gate` | `gate(stage="full")` — the same licence decision **plus** `validate_strix_binding` |
| 13 | `Seal exactly the gated bytes for attestation` | `release_dependency_gate.py seal` | `seal` — refuses a non-`PASS` **and** a non-`full` report |

The licence decision in step 6 is the same function the final gate calls in step 12. There is one
decision implementation, not a prescreen copy of one.

`needs` path traversed: the gate is a single `workflow_call` job (`jobs.gate`). A caller composes
`gate` → `attest`, and any mock job models only the edge out of `jobs.gate`.

### No collection-bypass input exists

Verified by reading the current source:

- The workflow's `workflow_call` inputs are the release identity, ecosystems, lock/manifest paths,
  artifact and filenames. **None of them skips capture, skips the licence stage, or injects a
  verdict.** `test_workflow_is_reusable_and_never_branch_selectable` and
  `test_gate_has_no_bypass_of_any_kind` pin the absence of a bypass shape.
- Step 4 always runs; step 5 always runs; step 6 always runs. The only `if:` conditions in the
  workflow are the lock-only install guard and the two evidence-retention uploads
  (`test_failure_evidence_survives_the_failure_that_produced_it` asserts there are exactly three).
- A hand-written `evidence/<slug>.json` cannot manufacture a case. The expected set comes from the
  producer's own lock (`_enumerate_python`) and `Cargo.lock` (`_enumerate_cargo`), and
  `_scope_rows` refuses collected material that no declared ecosystem expects with
  `SCOPE_SET_MISMATCH`. Test: `test_collected_material_outside_every_expected_set_is_a_scope_mismatch`.

**Consequence, stated plainly: a denial case cannot be fed in as a bare JSON blob.** It must arrive
as something the real capture path genuinely collects — a distribution present in the lock, with a
real `sha256`, whose own metadata carries the case.

### The fixture-distribution shape: **refuted as currently specified**

The proposed shape — a locally authored fixture wheel in the caller's artifact whose metadata
declares `GPL-3.0-only` (or omits `License` entirely for `LICENSE_MISSING`) — is the right *idea*,
because the case then rides on metadata the real collection reads. It does **not** work against the
unmodified capture script, for a reason the owner must decide on before any run is scheduled:

- `parse_python_lock` skips every directive line (`if not line or line.startswith("-")`), so a lock
  may legitimately carry `--find-links ./wheels`, and step 2's `pip install` reads the **real lock**
  and would honor it.
- `release_dependency_capture_raw.sh:151` reconstructs a *plain* requirements file for `pip
  download` with `grep -oE '^[A-Za-z0-9._-]+==[^ ;]+'`, which **drops every `-`-prefixed
  directive**. Step 4's `pip download --no-deps --only-binary=:all:` therefore resolves against the
  default index only.

So a locally authored wheel installs in step 2 and then fails to download in step 4
(`ERROR: no fetched distribution for <name>==<version>`). The run would fail in collection, before
the licence decision — which is *not* the licence rejection the fixture is meant to demonstrate.

This is also a latent production defect independent of the fixture: a real release whose lock
carries `--index-url`, `--extra-index-url` or `--find-links` has those dropped for the download, so
step 4 either fails or fetches from the wrong index while step 2 installed from the right one.
**Reported as a follow-up, not fixed here** — preserving index/find-links directives into the plain
requirements file changes production collection semantics and needs the owner's decision.

Until that is resolved, the only collectible negative case is one whose distribution the default
index already serves, which conflicts with "never fetch or install any GPL/LGPL/AGPL package".

### A GPL-declaring fixture package is rejected

The coordinator has **retracted** the idea of authoring or installing a fixture package whose
metadata declares a copyleft identifier. It is not to be built. The two evidence classes are split
instead:

- **Per-reason denial codes stay unit-level.** A self-authored, **data-only** SPDX string is a valid
  input to the production decision functions, and `LICENSE_DENIED_GPL`, `LICENSE_DENIED_LGPL`,
  `LICENSE_DENIED_AGPL`, `LICENSE_UNPARSEABLE`, `LICENSE_UNRECOGNIZED`, `LICENSE_MISSING`,
  `LICENSE_SELECTION_REQUIRED` and `LICENSE_SELECTION_INVALID` are proven exactly there, by direct
  calls to `evaluate_dependency_license` / `declared_license_expression` in the existing
  `tests/test_release_dependency_gate.py`. Those SPDX strings are **not** extended into the real
  package-install path.
- **The real capture path is exercised with a self-authored artifact containing no forbidden
  source**, verified through a `LICENSE_MISSING` rejection. Nothing copyleft is fetched, declared or
  installed at any point.

Note that the refutation above still applies to the `LICENSE_MISSING` fixture, because it is also a
locally authored distribution: until the dropped-directive defect is decided, `pip download` in step
4 cannot fetch it.

### Naming discipline for the eventual run

What such a run can prove, and the only way it may be described:
**real collection → licence-missing rejection → Strix blocked → `mock_publish` gated by `needs`.**

It is **not** a "GPL real-collection-refusal E2E" and must never be called one. The per-reason
copyleft denials are unit-level decision evidence and belong in a separate, separately labelled
section of any report. The link between the real capture path and the decision function is for the
coordinator to review from the exact-head source; it is not established by this prose.

## Gap 2 — the `mock_publish` job's contract and its limits

Name: **`mock_publish`**. Never `publish`, `release`, or `deploy`, so no reader or later script
mistakes it for the release job.

What it verifies: **only that the gating edge behaves as the real caller's publish job would.** Its
`needs` and `if` must be character-identical to the real release workflow's publish job, and both
must be quoted side by side in the run's evidence. It models the *edge*, nothing else: it does not
show that a real publish job would not start, because it is not that job and does not share its
environment, permissions or triggers.

Prohibited in `mock_publish`, and unnecessary for the contract: any `permissions:` beyond
`contents: read`, any token or secret, any `environment:`, any tag creation, any release creation,
any registry credential, any upload to a registry. Its steps are `echo` only.

**The real publish job's `needs`/`if` cannot be quoted here.** The caller workflow is FMLS-owned and
is not present at this head, so the two conditions must be quoted from the FMLS caller at its exact
SHA when the run is proposed. This plan does not invent them.

### Judgement rule and the exact fields to read

A skipped job can still carry a `started_at` in GitHub's payload, so **nothing may be inferred from
an absent or present `started_at` alone.** Judge from the raw payload plus whether steps actually
executed:

From `GET /repos/{owner}/{repo}/actions/runs/{run_id}` — `id`, `head_sha` (must equal the fixture
commit exactly), `status`, `conclusion`.

From `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` per job — `name`, `status`,
`conclusion`, and the full `steps[]` array, reading each step's `name`, `status`, `conclusion` and
`number`.

Decision rules:

- **Gate refused**: the `gate` job has `conclusion == "failure"`, and the step named
  `Refuse a denied or unverifiable licence before any credential exists` has
  `conclusion == "failure"`. The reason code is read from the
  `release-dependency-license-report` artifact's `failures[].code`, not from log prose.
- **Strix never started**: every step from `Provision the zero-cost review gateway for Strix`
  through `Run Strix against one isolated synthetic fixture per dependency` has
  `conclusion == "skipped"`. A step that ran and failed is a different outcome and must not be
  reported as "did not start".
- **Credentials were never required for the licence decision**: the step
  `Require every Strix provider credential before the Strix stage starts` also has
  `conclusion == "skipped"`, which places it after the licence refusal.
- **`mock_publish` did not execute**: its `conclusion == "skipped"` **and** its `steps[]` is empty or
  every entry has `conclusion == "skipped"`. `started_at` is recorded verbatim and explicitly **not**
  used as evidence either way.
- **Evidence survived the failure**: the `release-dependency-license-report` artifact exists on the
  failed run, which is the behavior the bound-to-producing-step upload condition exists to provide.

Anything not on this list stays unverified.

## Remaining end-to-end verification scope

Splitting the evidence into unit-level denials and one `LICENSE_MISSING` collection run does **not**
shrink the requirement, and nothing here may be marked fully complete. Still unproven, with the kind
of run that would prove each:

| Unproven | What would prove it |
|---|---|
| A copyleft dependency is refused by the **real collection path** | A run whose collected metadata carries a denied licence. No such run is planned, because authoring or installing a copyleft-declaring package is rejected. This gap stays open by policy. |
| `release_dependency_capture_raw.sh` executes at all | Any hosted run that reaches step 4. No step of that script has ever executed, here or in CI. |
| A locally authored fixture distribution is collectible | Resolution of the dropped-directive defect above, then one non-deploy run. |
| Strix succeeds and produces a real binding | A credentialed run that reaches step 12 with `verdict` and `findings` from an actual scan. |
| `seal` output is accepted by the real attestation workflow on real bytes | A run composing `gate` → `attest` on a real wheel and sdist. Locally only the *shape* is checked, against a synthetic sealed directory. |
| Capture/hash/metadata/artifact binding agree end to end | The same composed run, comparing `wheel_sha256` and `sdist_sha256` against the published artifact digests. |
| A real publish job would not start | Nothing planned proves this. `mock_publish` models the gating edge only. |

## What remains unverified without a hosted run

Verified locally by execution: every reason code above, produced by the production functions through
the existing harness in `tests/test_release_dependency_gate.py` and its siblings.

Not verified, and not claimable until a single approved non-deploy run exists: that the gate job
concludes `failure` on a real runner; that the Strix steps report `skipped`; that `mock_publish`
does not execute; that the capture script's real `pip inspect`/`pip download`/`cargo metadata`
invocations behave as read (no step of `release_dependency_capture_raw.sh` has ever been executed,
here or in CI); that `seal` and `exact-artifact-sbom-attestation.yml` agree on real bytes; and that
the fixture distribution is collectible at all, which the refutation above says it currently is not.

Refs #2342, #2347.
