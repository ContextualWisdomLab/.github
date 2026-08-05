# Sandboxed Output Resource Bounds Design

## Status

Approved for autonomous implementation under issue #766. This slice is stacked after PR #764 so it reuses the complete evidence-redaction boundary without changing reviewer identities or credentials.

## Problem

The central verification wrappers currently capture short-lived child stdout and stderr through pipes that are later consumed as complete values, while long-running services write unbounded log files. Redaction happens only after those streams have already been buffered or persisted. A defective or adversarial repository process can therefore consume runner memory or disk before its output reaches the redaction boundary. The current service-tail helper also reads the complete log before selecting the final lines.

## Rejected approach: process-wide file-size limits

POSIX `RLIMIT_FSIZE` limits every regular file created by a process, not only stdout and stderr. Applying it to a repository test or build command would incorrectly cap coverage databases, compiled assets, archives, temporary databases, and other legitimate artifacts. The output boundary must constrain evidence streams without changing application file semantics.

## Decision

Continuously drain child pipes on dedicated background threads into fixed-size final-suffix buffers:

- every short-lived command receives structured stdout and stderr pipes;
- one reader thread per stream drains fixed-size chunks so the OS pipe cannot fill and deadlock the child;
- each reader retains at most the configured final byte suffix;
- the first stream overflow atomically marks the result and kills the isolated POSIX process group;
- backend and frontend combined output uses the same bounded drainer and writes only the rendered bounded suffix to its evidence file; and
- service-tail publication seeks from the end of the already bounded file rather than reading the complete file.

The wrapper fails closed on platforms without POSIX process-group termination. It never falls back to `communicate()` or an unbounded file.

## Architecture

### `scripts/ci/bounded_subprocess.py`

A focused reusable module owns the evidence-stream boundary:

- `BoundedOutputCapture` continuously drains one binary stream into a locked final-suffix byte buffer;
- `BoundedCompletedProcess` exposes immutable bounded text, return code, and the output-limit flag;
- `BoundedTimeoutExpired` carries only bounded text evidence;
- `start_bounded_capture()` supports both short-lived streams and a bounded destination file;
- `run_bounded_command()` launches structured argv with `shell=False`, `start_new_session=True`, two independent drainers, timeout handling, and process-group termination;
- `kill_process_group()` kills only a still-running isolated POSIX group;
- `read_bounded_suffix()` performs a seek-from-end file read with replacement decoding; and
- numeric configuration validation rejects Boolean, undersized, oversized, or noninteger budgets.

The rendered truncated form includes one stable marker and still occupies no more than the declared stream budget.

### `scripts/ci/sandboxed_verify.py`

A new `--output-limit-bytes` option defaults to 1 MiB per stream. The existing `run_command` facade delegates to the bounded runner. Ordinary output and exit codes remain unchanged. Timeout remains 124. An attempted output overflow or unsupported platform returns 123. Result evidence adds the declared budget and a Boolean output-limit field.

### `scripts/ci/sandboxed_web_e2e.py`

A new `--output-limit-bytes` controls the E2E command and `--service-log-limit-bytes` defaults to 4 MiB per backend/frontend service. `start_service()` uses a combined pipe and bounded capture. Overflow terminates that service group. `stop_service()` finalizes its bounded evidence file. `tail_text()` reads at most 64 KiB from the end, retains at most 80 final lines, and applies the existing redaction boundary.

## Data flow

1. Parse and validate byte budgets before copying or running repository content.
2. Launch each child in a new POSIX session with structured argv and a scrubbed environment.
3. Start reader threads immediately and drain fixed 64 KiB chunks.
4. Retain only the final configured bytes under a lock.
5. On the first excess byte, mark the stream and kill the child process group exactly once.
6. On completion or timeout, join both readers and decode only bounded evidence.
7. Redact the evidence before printing or JSON serialization.
8. For services, persist only the bounded rendered suffix and later read only a bounded tail.

No credential value, complete oversized stream, or process-wide application-file restriction enters a public evidence sink.

## Failure semantics

- Invalid byte budgets fail argument parsing before execution.
- Unsupported process-group platforms fail closed with exit code 123 and a credential-free message.
- Timeout remains 124, even when bounded partial output exists.
- Output overflow is 123 and cannot be converted into child success.
- An ordinary nonzero child exit remains unchanged when no stream exceeded its budget.
- Service readiness failure remains 125 unless a more specific service output limit occurred.
- Reader failures and reader-join timeouts are explicit errors rather than silently discarded evidence.
- Cleanup and result emission run for every wrapper path.

## Verification

Real child-process tests prove:

- ordinary Unicode stdout/stderr remain intact within the budget;
- stdout and stderr floods are drained, bounded, and terminate with nonzero output-limit evidence;
- timeout evidence is bounded and remains exit 124;
- final-suffix retention preserves the last diagnostic bytes;
- service log floods terminate the service and persist no more than the declared evidence budget;
- suffix reading tolerates a partial UTF-8 code point and never requests an unbounded read;
- non-POSIX environments fail closed;
- reader exceptions and stuck-reader joins surface explicitly;
- CLI minima/maxima and result fields are deterministic; and
- existing environment, copy, cleanup, redaction, SSRF, and process-group tests remain green.

Every changed production helper requires a docstring and 100% statement/branch coverage.

## Standards and evidence boundary

Python documents that `PIPE` creates child stream pipes and that callers may manage `Popen` streams directly rather than asking `communicate()` to accumulate complete output. Structured argv and `shell=False` avoid shell interpretation. POSIX process groups provide one termination boundary for the child and its descendants. CWE-770 recommends explicit resource ceilings and throttling, and NIST SP 800-218 supplies the secure-development framework for preventing and verifying resource-exhaustion failures.

This design does not claim cross-platform equivalence. It deliberately supports the Linux/POSIX GitHub runner boundary and fails closed elsewhere.

## Non-goals

- changing scheduler cadence or scheduled review agents;
- changing OpenCode, Noema, Strix, NVIDIA NIM, or reviewer credentials;
- limiting repository workspace-copy size in this slice;
- limiting child CPU, address space, process count, application artifact size, or network traffic;
- replacing the existing output-redaction policy; or
- retaining complete oversized logs as downloadable artifacts.
