# Sandboxed Output Resource Bounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound memory and retained disk consumed by sandbox child output before redaction while retaining useful, credential-free final diagnostic suffixes.

**Architecture:** Launch structured commands in isolated POSIX process groups and continuously drain stdout/stderr pipes on dedicated threads into fixed-size final-suffix buffers. Kill the process group on first overflow; persist only bounded service evidence and read only bounded file suffixes.

**Tech Stack:** Python 3.10+, `subprocess.Popen`, POSIX process groups, `threading`, `pathlib`, pytest, pytest-cov, interrogate.

## Global Constraints

- Stack after PR #764 and preserve its complete output-redaction boundary.
- Keep structured argument vectors and `shell=False`.
- Do not apply process-wide `RLIMIT_FSIZE`; repository commands must retain ordinary application/build file semantics.
- Do not change OpenCode, Noema, Strix, NVIDIA NIM, reviewer identities, or credential names/scopes.
- Fail closed when POSIX process-group termination is unavailable.
- Timeout exit code remains 124; service readiness remains 125; output resource limit is 123.
- Default short-command budget is 1,048,576 bytes per stream.
- Default long-running service-log budget is 4,194,304 bytes per service.
- Maximum configurable budget is 67,108,864 bytes.
- Every changed production helper has a docstring and 100% statement/branch coverage.
- Add realistic child-process and file-boundary tests.
- Update `CHANGELOG.md` and APA 7 doctoring.

---

### Task 1: Define failing bounded-stream contracts

**Files:**
- Create: `tests/test_bounded_subprocess.py`

**Interfaces:**
- Consumes: wished-for `scripts.ci.bounded_subprocess`
- Produces: exact public API and bounded drain semantics

- [ ] **Step 1: Write ordinary-output and suffix tests**

Use real private files containing Unicode and a partial UTF-8 code point. Assert that suffix reads are byte-bounded and replacement-decoded.

- [ ] **Step 2: Write real stdout/stderr flood tests**

Launch `sys.executable -c` children that repeatedly call `os.write()`. Assert bounded final evidence, an output-limit flag, process-group termination, and no pipe deadlock.

- [ ] **Step 3: Write timeout and ordinary exit tests**

Assert normal Unicode output and return codes are preserved. Assert timeout raises bounded text evidence.

- [ ] **Step 4: Write capture destination and failure tests**

Prove final-suffix retention, bounded destination files, single overflow notification, reader-error propagation, and stuck-reader detection.

- [ ] **Step 5: Run the focused test and verify RED**

Run: `python -m pytest tests/test_bounded_subprocess.py -q`

Expected: import failure because the production module does not exist.

- [ ] **Step 6: Commit the failing tests**

```bash
git add tests/test_bounded_subprocess.py
git commit -m "test(ci): require bounded sandbox subprocess output"
```

### Task 2: Implement the reusable bounded pipe drainer

**Files:**
- Create: `scripts/ci/bounded_subprocess.py`
- Test: `tests/test_bounded_subprocess.py`

**Interfaces:**
- Produces:
  - `OUTPUT_LIMIT_EXIT_CODE = 123`
  - `DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES = 1_048_576`
  - `DEFAULT_SERVICE_LOG_LIMIT_BYTES = 4_194_304`
  - `MAXIMUM_OUTPUT_LIMIT_BYTES = 67_108_864`
  - `BoundedText`
  - `BoundedCompletedProcess`
  - `BoundedTimeoutExpired`
  - `BoundedOutputCapture`
  - `validate_output_limit(value, label) -> int`
  - `require_supported_platform() -> None`
  - `start_bounded_capture(...) -> BoundedOutputCapture`
  - `read_bounded_suffix(path, maximum_bytes) -> BoundedText`
  - `kill_process_group(process) -> None`
  - `run_bounded_command(args, cwd, env, timeout, evidence_limit_bytes) -> BoundedCompletedProcess`

- [ ] **Step 1: Implement immutable result types and validation**

Reject booleans, nonintegers, values below 4096, and values above 67,108,864.

- [ ] **Step 2: Implement one bounded stream capture**

Read fixed 64 KiB chunks on a daemon thread, retain only the final declared bytes, call the overflow callback exactly once, and optionally persist a rendered evidence file no larger than the declared budget.

- [ ] **Step 3: Implement process-group termination**

Require POSIX `killpg`, launch each command with `start_new_session=True`, and kill only a still-running group.

- [ ] **Step 4: Implement bounded command execution**

Create stdout and stderr pipes, start both drainers immediately, wait or timeout, kill the group when necessary, join both readers, and return or raise only bounded evidence.

- [ ] **Step 5: Implement bounded file suffix reads**

Seek from the end and never request an unbounded read. Use UTF-8 replacement and a stable truncation marker.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `python -m pytest tests/test_bounded_subprocess.py -q`

- [ ] **Step 7: Run focused coverage and docstrings**

Run branch coverage for the new module and interrogate production at 100%.

- [ ] **Step 8: Commit**

```bash
git add scripts/ci/bounded_subprocess.py tests/test_bounded_subprocess.py
git commit -m "feat(ci): bound child output with continuous pipe drains"
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

- [ ] **Step 2: Implement the minimal wrapper integration**

Validate the budget during argument parsing, print bounded text through existing redaction, map overflow to 123, and preserve timeout/nonzero behavior.

- [ ] **Step 3: Run focused tests and verify GREEN**

- [ ] **Step 4: Commit**

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
- `Service` carries its optional bounded capture and declared log limit.
- `tail_text(path, max_lines=80, max_bytes=65_536)` performs suffix-only reading.

- [ ] **Step 1: Write failing real-service tests**

Start children that exceed service and E2E budgets; assert exit 123, bounded evidence files/text, result fields, and cleanup. Add normal Unicode success, unsupported-platform, kept-sandbox, and suffix-delegation cases.

- [ ] **Step 2: Apply bounded drains to service and E2E children**

Use one combined bounded capture for each service and the shared two-stream runner for E2E. Check service overflow before or after readiness/E2E so it cannot be hidden by a generic status.

- [ ] **Step 3: Replace complete-file tail reads**

Seek from the end, decode with replacement, retain the final line count, and redact.

- [ ] **Step 4: Run focused tests and verify GREEN**

- [ ] **Step 5: Commit**

```bash
git add scripts/ci/sandboxed_web_e2e.py tests/test_sandboxed_web_e2e_output_limits.py
git commit -m "fix(ci): bound sandbox service and E2E logs"
```

### Task 5: Doctoring, changelog, and full validation

**Files:**
- Create: `docs/doctoring/sandboxed-output-resource-bounds.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Document the exact resource boundary**

Cover continuous pipe draining, bounded final-suffix memory, process-group termination, bounded service evidence, exit-code precedence, Linux/POSIX support, rejected process-wide file limits, and remaining CPU/workspace/network non-goals.

- [ ] **Step 2: Add APA 7 references**

Cite Python 3.14.6 `subprocess`, MITRE CWE-770 4.20, and NIST SP 800-218.

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
