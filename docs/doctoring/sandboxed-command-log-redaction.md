# Sandboxed command log redaction

## Decision

Captured `stdout` and `stderr` from repository verification and web end-to-end commands are untrusted evidence. Before those streams are written to GitHub Actions logs, they pass through the existing central `redact_text` boundary. The same rule applies to ordinary process completion and `TimeoutExpired` payloads represented as either text or bytes.

This change preserves the command exit status, line boundaries, non-sensitive diagnostics, machine-readable result envelope, isolated workspace, scrubbed environment, bounded timeouts, and service cleanup. It does not synthesize success, discard stderr, widen an environment allowlist, or alter the review gate.

## Threat model

A tool, test, package manager, browser runner, or application process can print credentials obtained from an explicitly allowed environment variable, configuration file, exception, dependency-manager diagnostic, or echoed request. CI logs are durable review evidence and can have a broader readership than the secret itself. Redaction therefore occurs at the final central output sink rather than relying on every child process to behave correctly.

MITRE classifies writing sensitive information to a log as CWE-532 and recommends not writing secrets to log files. OWASP likewise identifies access tokens, passwords, connection strings, encryption keys, and other primary secrets as data that should be removed, masked, sanitized, hashed, or encrypted before logging. The Python subprocess API does not implicitly select a system shell when `shell=False`; structured argument execution is retained independently of the log-redaction control.

## Verification contract

Permanent regression tests must prove that:

1. text and byte timeout payloads redact a PAT-shaped fixture;
2. normal sandbox verification stdout and stderr redact the same fixture;
3. normal sandboxed web E2E stdout and stderr redact the same fixture;
4. the raw fixture never appears in captured output;
5. ordinary non-sensitive text and process exit codes remain visible;
6. the test fixture is assembled from separate fragments so repository secret scanning does not mistake it for a live credential.

Exact-head repository tests, statement/branch coverage, docstring checks, Secret Scan, Semgrep, CodeQL, Security Scan, OpenCode, Noema, and branch protection remain authoritative.

## Modular boundary

Both wrappers remain independently executable scripts and reusable Python modules. They depend only on the central redaction utility and standard-library process primitives, so product repositories can consume the same behavior through the organization workflow without copying a repository-local implementation.

## References

MITRE. (2026, April 30). *CWE-532: Insertion of sensitive information into log file*. Common Weakness Enumeration. https://cwe.mitre.org/data/definitions/532.html

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

Python Software Foundation. (2026). *subprocess—Subprocess management* (Python 3.14.6 documentation). https://docs.python.org/3/library/subprocess.html
