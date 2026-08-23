# Sandboxed subprocess output resource bounds

## Decision

The central CI library now provides one reusable POSIX subprocess boundary that
continuously drains child stdout and stderr into fixed-size final-suffix buffers.
A stream that exceeds its declared byte budget terminates the isolated process
group. Exit code `123` is reserved for sandbox consumers that adopt this library;
consumer integration remains in separately reviewable stacked changes.

The default retained budgets are:

- 1,048,576 bytes for each short-lived command stream; and
- 4,194,304 bytes for each backend or frontend combined service stream.

Configurations below 4,096 bytes or above 67,108,864 bytes are rejected before repository code executes. Every normal-path output-reader join also has a finite 30-second bound.

## Why complete capture was unsafe

Python's `subprocess.PIPE` creates operating-system pipes for child standard streams. Waiting without concurrently reading can deadlock when a pipe fills, while `communicate()` solves that deadlock by accumulating the complete streams in parent memory. Neither behavior supplies an evidence-size ceiling. Long-running services that write directly to ordinary files similarly consume disk until the process or runner fails, and reading the complete file merely moves that unbounded allocation into parent memory.

The control plane therefore uses `Popen` directly, starts one reader thread per pipe immediately, reads fixed 64 KiB chunks, and retains only a locked final suffix. The first byte beyond a stream budget marks the result and kills the entire child process group created with `start_new_session=True`. Reader threads continue through EOF and are joined before bounded text is decoded or published.

A same-group descendant can retain an inherited stdout or stderr descriptor after
the direct child exits. The runner therefore signals the isolated process group
again after reaping the direct child and before joining its readers. A real
sentinel regression proves that such a descendant is stopped before it can act.
If a descendant deliberately creates a different session, every reader
finalization still has a 30-second bound, continues to finalize sibling readers,
and re-raises the first failure instead of holding the job until its workflow
timeout.

## Rejected process-wide file limit

POSIX file-size resource limits apply to every regular file written by the child process. A repository verification command may legitimately create coverage databases, compiled assets, archives, package artifacts, temporary databases, or generated fixtures larger than its log budget. Applying `RLIMIT_FSIZE` to the child would therefore change application and build behavior rather than only bounding evidence. The implemented boundary constrains stdout/stderr retention and leaves ordinary repository file semantics unchanged.

## Short-lived command boundary

`bounded_subprocess.run_bounded_command()`:

1. validates a structured, nonempty argument vector and positive timeout;
2. requires POSIX process-group termination and launches with `shell=False` and `start_new_session=True`;
3. connects stdout and stderr to independent binary pipes;
4. drains both pipes concurrently into separate bounded final-suffix buffers;
5. kills the process group on the first stream overflow;
6. kills the group on timeout and again after direct-child exit so same-group
   descendants cannot retain inherited pipes; joins both readers through the
   finite normal-path bound; and
7. returns or raises only bounded evidence.

A truncation marker is included inside, not in addition to, the declared retained byte budget. Reader errors and reader-join timeouts are explicit failures.

## Deferred consumer integration

The second stack layer adopts the library in `sandboxed_verify.py` for
short-lived verification commands. Long-running `sandboxed_web_e2e.py` service
evidence remains a separate layer. Keeping those integrations separate prevents
a shared process primitive, workspace symlink policy, and E2E result schema from
becoming one monolithic review.

The verification consumer maps an executable lookup failure to exit code `127`,
publishes its normal machine-readable failed result, and tells the operator to
install the executable or correct `PATH`. Provider and host path details do not
escape through an uncaught traceback.

## Security and availability properties

- Parent retained memory is bounded independently for stdout and stderr.
- Child pipes are continuously drained, preventing a full pipe from blocking the child indefinitely.
- Process-group termination covers ordinary descendants that retain inherited pipe descriptors.
- A same-group descendant that outlives the direct child is terminated before
  reader finalization; a different-session descendant cannot create an unbounded
  reader join.
- Structured argv and `shell=False` remain unchanged.
- Environment scrubbing, workspace copying, readiness polling, and
  machine-readable consumer evidence remain independent follow-up controls.
- Non-POSIX environments fail closed rather than using unmanaged capture.
- UTF-8 replacement decoding cannot expand published text beyond the configured
  byte budget.
- Bounded regular-file suffix reads account for both the truncation marker and
  replacement-decoding expansion inside the caller's declared byte budget.

MITRE CWE-770 identifies unbounded memory and other resource consumption as an availability weakness and recommends explicit minimum/maximum expectations, throttling, quotas, and safe failure when limits are reached. This implementation sets explicit per-stream ceilings, a finite finalization bound, and a stable failure result. NIST SP 800-218 supplies the secure-development framework used to define, test, and retain this control as reviewable evidence.

No formal CWE, NIST, or POSIX conformity is claimed.

## Verification contract

Real subprocess tests exercise:

- ordinary Korean Unicode stdout and stderr;
- infinite stdout and stderr floods;
- timeout with partial output;
- a real same-group descendant that inherits the pipes, outlives the direct
  child, and is prevented from writing a delayed sentinel;
- final-suffix retention and one overflow callback;
- partial UTF-8 suffix decoding;
- UTF-8 replacement expansion within the declared byte budget;
- bounded file reads;
- unsupported-platform failure;
- invalid budgets;
- reader exceptions, stuck-reader joins, a common finite join bound, and sibling finalization after the first failure;
- deterministic return and timeout evidence.

The exact pull-request head must additionally pass the complete central test suite, 100% production statement and branch coverage for the changed surface, production docstrings, Secret Scan, CodeQL, Semgrep, Python Security, dependency and supply-chain checks, OpenCode, Noema, CodeRabbit, independent current-head approval, and branch protection.

## Limitations

This slice does not limit:

- repository workspace-copy size;
- application/build artifacts written outside standard streams;
- CPU time beyond the existing command timeouts;
- address space, process count, network traffic, or external service response size; or
- output generated by an unrelated process that does not inherit the managed service pipes.

The reader buffers intentionally retain the final suffix rather than the complete beginning of an oversized stream because terminal diagnostics normally contain the most actionable failure evidence. Complete oversized logs are not retained as artifacts.

The finite reader join converts an inherited descriptor outside the managed
process group into a deterministic failure, but it does not discover or
terminate arbitrary processes in another session. Isolation beyond that
boundary remains the responsibility of the surrounding container or runner.
After the direct child is reaped, final same-group cleanup uses its numeric
process-group identifier immediately. POSIX does not provide a retained
process-group handle, so an extremely narrow identifier-reuse race remains a
platform limitation; a stronger isolation boundary belongs in the surrounding
container or runner.

## Rollback

Rollback must restore a different proven stdout/stderr memory bound before any
consumer relies on complete pipe capture. Reverting the process-group cleanup,
bounded suffix, or finite reader join independently would recreate an unbounded
or lingering-child path around the remaining controls.

## APA 7 references

MITRE Corporation. (2026). *CWE-770: Allocation of resources without limits or throttling* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/770.html

Python Software Foundation. (2026). *subprocess—Subprocess management* (Python 3.14.6 documentation). https://docs.python.org/3.14/library/subprocess.html

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). National Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

The Open Group, & IEEE. (2024). *The Open Group Base Specifications Issue 8:
Definitions* (IEEE Std 1003.1-2024). https://pubs.opengroup.org/onlinepubs/9799919799/basedefs/V1_chap03.html
