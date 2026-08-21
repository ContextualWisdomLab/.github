# Sandboxed subprocess output resource bounds

## Decision

The central sandbox wrappers continuously drain child stdout and stderr into fixed-size final-suffix buffers before publication-stage processing. A stream that exceeds its declared byte budget terminates the isolated POSIX process group and produces stable exit code `123`. Timeout remains `124`; service-readiness failure remains `125` unless a more specific output limit occurred.

The default retained budgets are:

- 1,048,576 bytes for each short-lived command stream; and
- 4,194,304 bytes for each backend or frontend combined service stream.

Configurations below 4,096 bytes or above 67,108,864 bytes are rejected before repository code executes. Every normal-path output-reader join also has a finite 30-second bound.

## Why complete capture was unsafe

Python's `subprocess.PIPE` creates operating-system pipes for child standard streams. Waiting without concurrently reading can deadlock when a pipe fills, while `communicate()` solves that deadlock by accumulating the complete streams in parent memory. Neither behavior supplies an evidence-size ceiling. Long-running services that write directly to ordinary files similarly consume disk until the process or runner fails, and reading the complete file merely moves that unbounded allocation into parent memory.

The control plane therefore uses `Popen` directly, starts one reader thread per pipe immediately, reads fixed 64 KiB chunks, and retains only a locked final suffix. The first byte beyond a stream budget marks the result and kills the entire child process group created with `start_new_session=True`. Reader threads continue through EOF and are joined before bounded text is decoded or published.

A descendant can intentionally create a new session while retaining an inherited stdout or stderr descriptor. The original process group can then terminate while the escaped descendant keeps the pipe open. For that reason, every ordinary reader finalization passes the 30-second join bound to each capture, continues to finalize sibling readers, and then re-raises the first failure. A reader still alive after that bound produces the explicit `bounded output drain did not finish` failure instead of holding the job until its outer workflow timeout.

## Rejected process-wide file limit

POSIX file-size resource limits apply to every regular file written by the child process. A repository verification command may legitimately create coverage databases, compiled assets, archives, package artifacts, temporary databases, or generated fixtures larger than its log budget. Applying `RLIMIT_FSIZE` to the child would therefore change application and build behavior rather than only bounding evidence. The implemented boundary constrains stdout/stderr retention and leaves ordinary repository file semantics unchanged.

## Short-lived command boundary

`bounded_subprocess.run_bounded_command()`:

1. validates a structured, nonempty argument vector and positive timeout;
2. requires POSIX process-group termination and launches with `shell=False` and `start_new_session=True`;
3. connects stdout and stderr to independent binary pipes;
4. drains both pipes concurrently into separate bounded final-suffix buffers;
5. kills the process group exactly once when either stream exceeds its budget;
6. kills the group on timeout and joins both readers through the finite normal-path bound; and
7. returns or raises only bounded evidence.

A truncation marker is included inside, not in addition to, the declared retained byte budget. Reader errors and reader-join timeouts are explicit failures.

## Long-running service boundary

Each backend and frontend uses one combined stdout/stderr pipe and the same bounded drainer. The capture retains the final suffix in memory and writes only its bounded rendered form to the private sandbox log file when the stream closes. The evidence file therefore cannot exceed the declared service-log budget.

Service overflow is checked during readiness, after E2E execution, and after service shutdown. It takes precedence over an ordinary command or readiness result, but a true E2E timeout remains `124`. `tail_text()` reads no more than 65,536 bytes from the end of the already bounded file, retains the configured final line count, and keeps the truncation marker visible. The machine-readable result separates `output_limited`, `output_limit_unsupported`, and `service_capture_failed` so consumers can distinguish a byte-budget breach, unavailable enforcement, and cleanup failure. Credential redaction remains a separate active integration line and is not claimed by this slice.

If orderly service or capture finalization raises, the wrapper makes a second
best-effort process-group kill and bounded reap before publishing resource
failure evidence. A capture error therefore cannot silently leave the backend
or frontend process group running after the ordinary shutdown path aborts.

A realistic regression gives the flooding backend an actual readiness URL and configures the E2E command to create a sentinel file. The overflow result must be emitted while the sentinel remains absent, proving that readiness handling cannot silently execute an ordinary E2E command before acknowledging the service evidence limit.

## Security and availability properties

- Parent retained memory is bounded independently for stdout and stderr.
- Service evidence disk use is bounded per service.
- Child pipes are continuously drained, preventing a full pipe from blocking the child indefinitely.
- Process-group termination covers ordinary descendants that retain inherited pipe descriptors.
- A descendant that escapes the original group cannot create an unbounded reader join.
- Structured argv and `shell=False` remain unchanged.
- Environment scrubbing, timeout enforcement, process cleanup, SSRF-safe readiness polling, and machine-readable evidence remain independent controls. The bounded capture is intentionally composable with the separately reviewed credential-redaction line.
- Non-POSIX environments fail closed rather than using unmanaged capture.
- Output overflow cannot be converted into success by the child process or into an E2E execution by readiness short-circuiting.

MITRE CWE-770 identifies unbounded memory and other resource consumption as an availability weakness and recommends explicit minimum/maximum expectations, throttling, quotas, and safe failure when limits are reached. This implementation sets explicit per-stream ceilings, a finite finalization bound, and a stable failure result. NIST SP 800-218 supplies the secure-development framework used to define, test, and retain this control as reviewable evidence.

No formal CWE, NIST, or POSIX conformity is claimed.

## Verification contract

Real subprocess tests exercise:

- ordinary Korean Unicode stdout and stderr;
- infinite stdout and stderr floods;
- timeout with partial output;
- final-suffix retention and one overflow callback;
- bounded persisted service evidence;
- service overflow before or during readiness/E2E, including a sentinel proof that E2E never ran;
- ordinary backend/frontend/E2E success and cleanup;
- partial UTF-8 suffix decoding;
- bounded file reads;
- unsupported-platform failure;
- invalid budgets;
- reader exceptions, stuck-reader joins, a common finite join bound, and sibling finalization after the first failure;
- retained redaction of credentials in output, commands, notes, structured JSON, and service tails; and
- deterministic result fields and exit-code precedence.

The exact pull-request head must additionally pass the complete central test suite, 100% production statement and branch coverage for the changed surface, production docstrings, Secret Scan, CodeQL, Semgrep, Python Security, dependency and supply-chain checks, OpenCode, Noema, CodeRabbit, independent current-head approval, and branch protection.

## Limitations

This slice does not limit:

- repository workspace-copy size;
- application/build artifacts written outside standard streams;
- CPU time beyond the existing command timeouts;
- address space, process count, network traffic, or external service response size; or
- output generated by an unrelated process that does not inherit the managed service pipes.

The reader buffers intentionally retain the final suffix rather than the complete beginning of an oversized stream because terminal diagnostics normally contain the most actionable failure evidence. Complete oversized logs are not retained as artifacts.

The finite reader join converts an escaped inherited descriptor into a deterministic failure, but it does not discover or terminate arbitrary processes outside the original process group. Isolation beyond that boundary remains the responsibility of the surrounding container or runner.

## Rollback

Rollback must restore a different proven memory-and-disk bound for every short-lived and long-running publication path. Reverting only the process-group kill, service capture, suffix reader, or finite reader join would recreate an unbounded path around the remaining controls. Before rollback, operators must demonstrate realistic flood tests, bounded retained memory and files, finite finalization, timeout behavior, cleanup and exact-head independent review.

## APA 7 references

MITRE Corporation. (2026). *CWE-770: Allocation of resources without limits or throttling* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/770.html

Python Software Foundation. (2026). *subprocess—Subprocess management* (Python 3.14.6 documentation). https://docs.python.org/3.14/library/subprocess.html

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
