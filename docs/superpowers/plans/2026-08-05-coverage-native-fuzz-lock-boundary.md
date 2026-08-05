# Coverage Native-Fuzz Lock Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent native fuzz-engine toolchain locks from entering generic OpenCode coverage images while retaining hash-pinned property and test dependencies.

**Architecture:** Add one exact-name lock-role classifier to the trusted-base Python dependency materializer and evaluate it before blob selection. Protect the boundary with real temporary-Git fixtures, 100% production statement/branch coverage, docstrings, and source-backed doctoring.

**Tech Stack:** Python 3.10+, `pathlib`, Git CLI read-only commands, pytest, pytest-cov.

## Global Constraints

- Continue reading dependency metadata only from the validated base commit.
- Do not change OpenCode, Noema, Strix, NVIDIA NIM, or reviewer credential names/scopes.
- Do not weaken `--require-hashes`, output bounds, symlink rejection, or malformed-tree failure.
- Every changed production helper must have a docstring and 100% statement/branch coverage.
- Document current authoritative sources in APA 7 format.
- Update `CHANGELOG.md`.

---

### Task 1: Add failing real-repository coverage-role evidence

**Files:**
- Create: `tests/test_coverage_native_fuzz_lock_boundary.py`

**Interfaces:**
- Consumes: `materializer.materialize(repo, base_sha, output)`
- Produces: a fixture proving `requirements-atheris.txt` is excluded while property/test locks remain

- [ ] **Step 1: Create a temporary Git base with three hash locks**

Add:

- `fuzz/requirements-atheris.txt`;
- `fuzz/requirements-property.txt`;
- `services/example/requirements-fuzz-regression.txt`.

- [ ] **Step 2: Assert only the latter two enter the manifest**

The exact Atheris name must be absent. The nonexact similarly named lock proves the classifier is not substring-based.

- [ ] **Step 3: Run the focused test and verify RED**

Run: `python -m pytest tests/test_coverage_native_fuzz_lock_boundary.py -q`

Expected: FAIL because all three files are currently selected.

- [ ] **Step 4: Commit the failing test**

```bash
git add tests/test_coverage_native_fuzz_lock_boundary.py
git commit -m "test(coverage): exclude native fuzz engine locks"
```

### Task 2: Implement the exact-name lock-role boundary

**Files:**
- Modify: `scripts/ci/materialize_base_python_requirements.py`

**Interfaces:**
- Produces: `_is_native_fuzz_engine_lock_name(name: str) -> bool`
- Updates: `_is_candidate_lock_name(name: str) -> bool`

- [ ] **Step 1: Add an immutable exact-name set**

The initial set contains only `requirements-atheris.txt`.

- [ ] **Step 2: Add the pure classifier with explanatory docstring**

Return true only for exact members of the immutable set.

- [ ] **Step 3: Exclude the native toolchain before ordinary candidate matching**

Keep every existing candidate and content check unchanged for other files.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_coverage_native_fuzz_lock_boundary.py -q`

Expected: PASS.

- [ ] **Step 5: Run coverage and docstring gates**

Run the repository's full Python test, branch-coverage, compile, formatting, static-security, and interrogate commands.

- [ ] **Step 6: Commit**

```bash
git add scripts/ci/materialize_base_python_requirements.py tests/test_coverage_native_fuzz_lock_boundary.py
git commit -m "fix(coverage): skip native fuzz engine locks"
```

### Task 3: Record doctoring and release evidence

**Files:**
- Create: `docs/doctoring/coverage-native-fuzz-lock-boundary.md`
- Create or modify: `CHANGELOG.md`

**Interfaces:**
- Produces: operational rationale, standards traceability, and Unreleased evidence

- [ ] **Step 1: Document the role boundary**

Record why Atheris belongs to dedicated fuzz execution rather than generic import coverage, the immutable-base trust boundary, limitations, and rollback.

- [ ] **Step 2: Add APA 7 references**

Cite official Atheris, Python packaging, coverage.py, and Semgrep/GitHub Actions material relevant to the decision.

- [ ] **Step 3: Update the changelog**

Add the generic coverage materializer correction under `Unreleased / Fixed`.

- [ ] **Step 4: Run full exact-slice verification and commit**

```bash
git add docs/doctoring/coverage-native-fuzz-lock-boundary.md CHANGELOG.md
git commit -m "docs(coverage): record native fuzz lock boundary"
```

### Task 4: Validate, review, and integrate

- [ ] **Step 1: Open a focused PR closing #762**
- [ ] **Step 2: Resolve every automated and human review finding**
- [ ] **Step 3: Re-run all exact-head central checks and independent review**
- [ ] **Step 4: Merge without administrative bypass**
- [ ] **Step 5: Re-dispatch coverage review for contextual-orchestrator #96 and merge it when green**
- [ ] **Step 6: Rebase/revalidate contextual-orchestrator #76, then continue its dependency-ordered PR queue**
