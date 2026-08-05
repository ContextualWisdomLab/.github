# Sandboxed Output Resource Bounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound memory and disk consumed by sandbox child output before redaction while retaining useful, credential-free diagnostic suffixes.

**Architecture:** Redirect child streams to private regular files and lower POSIX `RLIMIT_FSIZE` in the child pre-exec boundary. A reusable bounded-subprocess module classifies ordinary completion, timeout, and output overflow; both sandbox wrappers expose validated byte budgets and preserve their existing result contracts.

**Tech Stack:** Python 3.10+, POSIX `resource`, `subprocess`, `tempfile`, `pathlib`, pytest, pytest-cov, interrogate.

## Global Constraints

- Stack after PR #764 and preserve its complete output-redaction boundary.
- Keep structured argument vectors and `shell=False`.
- Do not change OpenCode, Noema, Strix, NVIDIA NIM, reviewer identities, or credential names/scopes.
- Fail closed when POSIX file-size limits are unavailable.
- Timeout exit code remains 124; service readiness remains 125; output resource limit is 123.
- Default short-command budget is 1,048,576 bytes per stream.
- Default long-running service-log budget is 4,194,304 bytes per service.
- Maximum configurable budget is 67,108,864 bytes.
- Every changed production helper has a docstring and 100% statement/branch coverage.
- Add realistic child-process and file-boundary tests.
- Update `CHANGELOG.md` and APA 7 doctoring.

---

### Task 1: Define failing bounded-subprocess contracts

**Files:**
- Create: `tests/test_bounded_subprocess.py`

**Interfaces:**
- Consumes: wished-for `scripts.ci.bounded_subprocess`
- Produces: exact public API and resource-limit semantics

- [ ] **Step 1: Write ordinary-output and suffix tests**

Use real private files containing Unicode and a partial UTF-8 leading byte. Assert that `read_bounded_suffix(path, maximum_bytes)` reads only the final budget, adds one truncation marker when needed, and uses replacement decoding rather than failing.

- [ ] **Step 2: Write real child overflow tests**

Launch `sys.executable -c` children that repeatedly call `os.write()` on stdout and stderr. Assert that each capture file is no larger than evidence budget plus one byte, `output_limited` is true, and the returned text is bounded.

- [ ] **Step 3: Write timeout and ordinary exit tests**

Assert normal Unicode output and return codes are preserved. Assert timeout raises `BoundedTimeoutExpired` with bounded stdout/stderr.

- [ ] **Step 4: Write platform and configuration tests**

Monkeypatch the platform/resource surface to prove unsupported environments fail closed, smaller existing hard limits are retained, and budgets outside 4 KiB–64 MiB are rejected.

- [ ] **Step 5: Run focused tests and verify RED**

Run: `python -m pytest tests/test_bounded_subprocess.py -q`

Expected: import failure because the production module does not exist.

- [ ] **Step 6: Commit the failing tests**

```bash
git add tests/test_bounded_subprocess.py
git commit -m "test(ci): require bounded sandbox subprocess output"
```

### Task 2: Implement the reusable POSIX output boundary

**Files:**
- Create: `scripts/ci/bounded_subprocess.py`
- Test: `tests/test_bounded_subprocess.py`

**Interfaces:**
- Produces:
  - `OUTPUT_LIMIT_EXIT_CODE = 123`
  - `DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES = 1_048_576`
  - `DEFAULT_SERVICE_LOG_LIMIT_BYTES = 4_194_304`
  - `MAXIMUM_OUTPUT_LIMIT_BYTES = 67_108_864`
  - `BoundedCompletedProcess`
  - `BoundedTimeoutExpired`
  - `validate_output_limit(value, label) -> int`
  - `bounded_file_preexec(evidence_limit_bytes) -> Callable[[], None]`
  - `read_bounded_suffix(path, maximum_bytes) -> BoundedText`
  - `file_limit_reached(path, evidence_limit_bytes, return_code) -> bool`
  - `run_bounded_command(args, cwd, env, timeout, evidence_limit_bytes) -> BoundedCompletedProcess`

- [ ] **Step 1: Implement immutable result types and validation**

Keep fields typed and frozen. Reject booleans, nonintegers, values below 4096, and values above 67,108,864.

- [ ] **Step 2: Implement POSIX pre-exec limiting**

Require `os.name == "posix"` and `resource.RLIMIT_FSIZE`. In the child, read the existing hard limit, choose the lower of budget-plus-one and the finite hard limit, then set soft and hard to that target.

- [ ] **Step 3: Implement bounded suffix reading and overflow classification**

Use binary seek-from-end and never call an unbounded read. Prefix `...[output truncated]...\n` only when the file exceeded the evidence budget.

- [ ] **Step 4: Implement short-lived command execution**

Create two private binary capture files, pass their descriptors to `subprocess.run`, apply the pre-exec function, read bounded suffixes in success and timeout paths, and remove the capture directory in all cases.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_bounded_subprocess.py -q`

Expected: PASS.

- [ ] **Step 6: Run focused coverage and docstrings**

Run coverage with branch measurement for the new module and interrogate the production file at 100%.

- [ ] **Step 7: Commit**

```bash
git add scripts/ci/bounded_subprocess.py tests/test_bounded_subprocess.py
git commit -m "feat(ci): bound child output with POSIX file limits"
```

### Task 3: Integrate bounded output into sandboxed verification

**Files:**
- Modify: `scripts/ci/sandboxed_verify.py`
- Create: `tests/test_sandboxed_verify_output_limits.py`
- Modify: existing sandbox verification tests as needed

**Interfaces:**
- Adds CLI: `--output-limit-bytes`
- `run_command(...)` delegates to `run_bounded_command`
- Result payload adds `output_limit_bytes` and `output_limited`

- [ ] **Step 1: Write failing wrapper tests**

Use real child commands to prove ordinary output, stdout overflow, stderr overflow, timeout, redaction, cleanup, result JSON, and stable exit codes.

- [ ] **Step 2: Run focused wrapper tests and verify RED**

Expected: missing CLI option and unbounded `run_command` behavior.

- [ ] **Step 3: Implement the minimal wrapper integration**

Validate the budget during argument parsing, print bounded text through existing redaction, map overflow to 123, and preserve timeout/nonzero behavior.

- [ ] **Step 4: Run focused tests and verify GREEN**

- [ ] **Step 5: Commit**

```bash
git add scripts/ci/sandboxed_verify.py tests/test_sandboxed_verify_output_limits.py
git commit -m "fix(ci): bound sandbox verification output"
```

### Task 4: Bound E2E service and command logs

**Files:**
- Modify: `scripts/ci/sandboxed_web_e2e.py`
- Create: `tests/test_sandboxed_web_e2e_output_limits.py`
- Modify: existing web E2E tests as needed

**Interfaces:**
- Adds CLI:
  - `--output-limit-bytes`
  - `--service-log-limit-bytes`
- `Service` records its evidence limit.
- `tail_text(path, max_lines=80, max_bytes=65_536)` performs suffix-only reading.

- [ ] **Step 1: Write failing real-service tests**

Start a child that exceeds the service log budget before readiness and assert exit 123, bounded file size, bounded redacted tail, and cleanup. Add a normal service/E2E case and a suffix-read spy that rejects unbounded reads.

- [ ] **Step 2: Run focused tests and verify RED**

- [ ] **Step 3: Apply resource limits to service and E2E children**

Use the shared pre-exec boundary for service files and shared command runner for E2E. Check service overflow before assigning readiness/E2E return codes.

- [ ] **Step 4: Replace complete-file tail reads**

Seek from the end, decode with replacement, retain the final line count, and redact.

- [ ] **Step 5: Run focused tests and verify GREEN**

- [ ] **Step 6: Commit**

```bash
git add scripts/ci/sandboxed_web_e2e.py tests/test_sandboxed_web_e2e_output_limits.py
git commit -m "fix(ci): bound sandbox service and E2E logs"
```

### Task 5: Doctoring, changelog, and full validation

**Files:**
- Create: `docs/doctoring/sandboxed-output-resource-bounds.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: operator evidence, limitations, rollback, APA 7 references

- [ ] **Step 1: Document the exact resource boundary**

Cover `RLIMIT_FSIZE`, budget-plus-one detection, suffix evidence, exit-code precedence, single-threaded pre-exec assumption, Linux/POSIX support, unsupported-platform failure, and remaining CPU/memory/process/network non-goals.

- [ ] **Step 2: Add APA 7 references**

Cite Python 3.14.6 `resource` and `subprocess`, MITRE CWE-770 4.20, NIST SP 800-218, and the POSIX resource-limit specification.

- [ ] **Step 3: Update `CHANGELOG.md`**

Record the memory/disk exhaustion correction under `Security` and the new bounded evidence behavior under `Changed`.

- [ ] **Step 4: Run complete exact-slice gates**

Run all central Python tests, 100% statement/branch coverage, 100% production docstrings, compile/static checks, Secret Scan, Semgrep, CodeQL, Python Security, and supply-chain checks.

- [ ] **Step 5: Commit**

```bash
git add docs/doctoring/sandboxed-output-resource-bounds.md CHANGELOG.md
git commit -m "docs(ci): record bounded sandbox output evidence"
```

### Task 6: Review and integration

- [ ] **Step 1: Open a stacked PR targeting `fix/sandboxed-log-redaction-clean` and closing #766**
- [ ] **Step 2: Resolve every exact-head automated and human finding**
- [ ] **Step 3: Merge #764 first without bypass**
- [ ] **Step 4: Retarget this PR to `main`, rerun every exact-head gate, and merge without bypass**
- [ ] **Step 5: Remove or update obsolete loops/docs only after both protections are present on `main`**
