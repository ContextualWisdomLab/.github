# Sandboxed Output Resource Bounds Design

## Status

Approved for autonomous implementation under issue #766. This slice is stacked after PR #764 so it can reuse the complete evidence-redaction boundary without changing reviewer identities or credentials.

## Problem

The central verification wrappers currently capture short-lived child stdout and stderr through pipes and let long-running services write ordinary log files. Redaction happens only after those streams have already been buffered or persisted. A defective or adversarial repository process can therefore consume runner memory or disk before its output reaches the redaction boundary. The current service-tail helper also reads the complete log before selecting the final lines.

## Decision

Use the operating system's POSIX file-size resource limit to bound every child-created output file before execution:

- redirect each short-lived command stream to a private regular file rather than `PIPE`;
- apply `resource.setrlimit(resource.RLIMIT_FSIZE, ...)` in the single-threaded child pre-exec boundary;
- set the kernel ceiling one byte above the evidence budget so the parent can distinguish exact-sized normal output from an attempted overflow;
- read at most the configured final suffix from each file;
- map any attempted overflow to one stable resource-limit exit code;
- run backend and frontend services with the same kernel-enforced file ceiling; and
- seek from the end of service logs, reading only a bounded byte suffix before applying the existing final-line and redaction rules.

The wrappers fail closed on platforms where POSIX resource limits are unavailable. They do not silently revert to unbounded capture.

## Architecture

### `scripts/ci/bounded_subprocess.py`

A focused reusable module owns child output limits. It provides:

- `BoundedCompletedProcess`: immutable command result with bounded text streams and an `output_limited` flag;
- `BoundedTimeoutExpired`: timeout evidence carrying only bounded text;
- `bounded_file_preexec(limit_bytes)`: a child-only callable that lowers `RLIMIT_FSIZE` without raising an existing hard limit;
- `run_bounded_command(...)`: structured-argv, `shell=False` execution into two private files;
- `read_bounded_suffix(path, maximum_bytes)`: suffix-only binary read with UTF-8 replacement and a stable truncation marker;
- `file_limit_reached(path, evidence_limit_bytes, return_code)`: exact overflow classification; and
- numeric configuration validation with explicit minimum and maximum values.

The module imports `resource` only on POSIX and raises one stable unsupported-platform error otherwise.

### `sandboxed_verify.py`

The existing `run_command` facade delegates to `run_bounded_command`. A new optional `--output-limit-bytes` argument defaults to 1 MiB per stream. Normal output and exit codes remain unchanged. Timeout remains exit code 124. Attempted output overflow emits bounded redacted evidence and returns exit code 123.

### `sandboxed_web_e2e.py`

A new `--output-limit-bytes` controls the short-lived E2E command. A separate `--service-log-limit-bytes` defaults to 4 MiB per service. `start_service` applies the kernel ceiling before exec. Readiness or E2E completion checks classify service log overflow and return exit code 123. `tail_text` reads no more than 64 KiB from the end of the file, then retains at most 80 final lines and redacts them.

## Data flow

1. Parse and validate byte budgets before copying or running repository content.
2. Create private capture files inside the isolated sandbox.
3. Spawn the child with structured argv, scrubbed environment, `shell=False`, and a lowered `RLIMIT_FSIZE`.
4. Wait for completion or timeout.
5. Read only bounded suffixes, close and delete capture files, then redact before publication.
6. Classify timeout, ordinary exit, or output limit in that order.
7. Emit the existing machine-readable result schema plus declared limit evidence.

No credential value, unbounded stream, or PR-controlled path enters a public evidence sink.

## Failure semantics

- Invalid byte budgets fail argument parsing before execution.
- Unsupported resource-limit platforms fail closed with stable exit code 123 and a credential-free message.
- Timeout remains 124, even when bounded partial output exists.
- Output overflow is 123 and cannot be converted to success by the child catching `SIGXFSZ` because file size greater than the evidence budget independently proves an attempted excess.
- An ordinary nonzero child exit remains unchanged when no stream exceeded its budget.
- Service readiness failure remains 125 unless a service log exceeded its budget, in which case the more specific 123 result wins.
- Cleanup and result emission run for every path.

## Verification

Real child-process tests must prove:

- ordinary Unicode stdout/stderr remain intact within the budget;
- stdout and stderr attempts above the limit cannot produce files larger than budget plus one byte;
- overflow returns 123 with bounded redacted evidence;
- timeout evidence is bounded and returns 124;
- service log overflow stops readiness and returns 123;
- suffix reading never calls an unbounded `read()` and tolerates a partial UTF-8 code point;
- non-POSIX or missing-`RLIMIT_FSIZE` environments fail closed;
- lower pre-existing hard limits are respected;
- CLI minima/maxima and new result fields are deterministic; and
- all existing environment, copy, cleanup, redaction, SSRF, and process-group tests remain green.

Every changed production helper requires a docstring and 100% statement/branch coverage.

## Standards and evidence boundary

Python 3.14 documents `resource.setrlimit()` as the resource-consumption control and `RLIMIT_FSIZE` as the maximum file size a process may create. Python's subprocess documentation states that `PIPE` captures child streams through `Popen`/`communicate`, whereas existing file descriptors may be supplied directly. CWE-770 recommends explicit resource ceilings and operating-system resource limiting. NIST SP 800-218 supplies the secure-development framework for preventing and verifying these failure modes.

This design does not claim cross-platform equivalence. It deliberately supports the Linux/POSIX GitHub runner boundary and fails closed elsewhere.

## Non-goals

- changing scheduler cadence or scheduled review agents;
- changing OpenCode, Noema, Strix, NVIDIA NIM, or reviewer credentials;
- limiting repository workspace-copy size in this slice;
- limiting child CPU, address space, process count, or network traffic;
- replacing the existing output-redaction policy;
- retaining complete oversized logs as downloadable artifacts.
