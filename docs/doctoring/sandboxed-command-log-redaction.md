# Sandboxed command and output redaction

## Decision

The central verification wrappers treat subprocess output, service log tails, command arguments, shell-command strings, and reviewer evidence notes as potentially sensitive before writing them to GitHub Actions logs or machine-readable review evidence.

One trusted redaction module owns this publication boundary:

- captured standard output and standard error are redacted before printing;
- `TimeoutExpired` byte and text payloads use the same redaction path;
- service log tails are redacted before publication;
- command arguments following sensitive options such as `--token`, `--password`, or `--api-key` are replaced;
- sensitive `KEY=value` command arguments are replaced while preserving the key;
- child-process text that echoes a sensitive option and its separate value is redacted even outside a structured command array;
- standalone provider-token shapes are removed;
- valid JSON is traversed recursively so credential-shaped object keys and string values cannot bypass line-oriented patterns;
- leading indentation is preserved when a valid JSON diagnostic is normalized;
- JSON-looking lines that are malformed, too deeply nested, or rejected by the parser or encoder are replaced as complete redacted records rather than retried through weaker handling;
- shell command strings are parsed without execution and reconstructed from redacted arguments; and
- JSON result markers redact commands and evidence notes before serialization.

The original argument vectors and output are used only inside the isolated execution boundary. Redaction changes neither the command that runs nor its exit status. It is applied at every publication sink instead of depending on each child process to avoid printing credentials.

## Threat model

Repository verification commands and web end-to-end services can emit credentials through exception messages, dependency-manager diagnostics, HTTP-client traces, command-line options, environment-derived configuration, startup logs, structured JSON diagnostics, and timeout payloads. An explicitly allowlisted environment variable can therefore remain correctly scoped to a child process and still be disclosed when that child echoes it.

GitHub Actions logs and review envelopes are durable evidence with a potentially broader readership than the originating credential. MITRE classifies insertion of sensitive information into log files as CWE-532. OWASP's current logging guidance identifies access tokens, passwords, database connection strings, encryption keys, and other primary secrets as values that should normally be removed, masked, sanitized, hashed, or encrypted before logging. NIST SSDF requires protection of software and development artifacts from unauthorized access and disclosure.

Untrusted tools can also emit malformed or deeply nested structured diagnostics. Recursive parsing without an explicit bound creates an availability risk. Treating a JSON-looking record as ordinary text after a syntax or recursion failure can also recreate a confidentiality bypass because the relationship between a sensitive object key and an otherwise ordinary string value has been lost. The redaction boundary therefore replaces the complete JSON-looking record on parse or encode failure and replaces a subtree at the configured maximum JSON depth.

## Security and availability boundaries

- No provider-shaped credential literal is committed as a test fixture. Tests construct credential-shaped values from fragments at runtime so Secret Scan remains authoritative.
- Redaction is fail-closed for recognized sensitive option names, assignments, bearer/basic values, JWTs, known provider token formats, and concatenated or CamelCase credential key names, but it is not a general data-loss-prevention engine.
- Sensitive option detection uses explicit credential terms. Ambiguous short flags such as `-p` are not guessed because they can mean port, path, project, or password depending on the child tool.
- A sensitive option with no value does not consume the next option-looking argument. This preserves command diagnostics while preventing an option name from being mistaken for the secret value.
- Shell strings are tokenized with `shlex.split`; no shell is invoked for redaction. Malformed shell strings fall back to line-oriented redaction.
- `subprocess.run` and `subprocess.Popen` receive structured argument arrays with `shell=False`. Preventing shell interpretation and preventing log disclosure are independent controls.
- The assignment scanner advances through each ordinary identifier once. A deterministic instrumentation test prevents a long non-sensitive token from reintroducing quadratic rescanning and log-processing denial of service.
- An oversized assignment key is conservatively classified as sensitive when followed by a value, preventing matcher-size limits from becoming a bypass.
- Structured JSON traversal stops at `MAX_JSON_DEPTH`; the remaining subtree is represented only as `[REDACTED]`.
- A JSON syntax error, parser `RecursionError`, or encoder `RecursionError` redacts the complete JSON-looking line while preserving indentation and its line ending. It never reprocesses the same record through a weaker parser.
- File paths, working directories, and sandbox paths remain visible operational evidence. Operators must not place credentials in path names.
- Redaction preserves line boundaries and ordinary non-sensitive diagnostics. It does not transform a failed command into a successful result or suppress a nonzero exit status.

No formal OWASP, NIST, or CWE conformity is claimed.

## Verification contract

The focused regression suite constructs credential-shaped values at runtime and proves that they do not appear in:

1. completed verification stdout or stderr;
2. timeout output supplied as bytes or text;
3. human-readable command displays;
4. echoed `--token value`, `--password value`, or `--api-key value` text;
5. JSON result-marker command arrays;
6. backend, frontend, or E2E shell-command fields;
7. reviewer evidence notes;
8. service log tails;
9. nested JSON string values;
10. JSON object keys, including concatenated and CamelCase credential names;
11. indented JSON diagnostics;
12. malformed JSON-looking diagnostics; or
13. a structured diagnostic beyond the supported JSON nesting depth.

The tests also cover separate sensitive options, `--option=value`, `KEY=value` assignments, standalone provider-token shapes, malformed shell quoting, missing logs, bounded final-line selection, recursive JSON structures, oversized assignment keys, bounded assignment scanning, parser and encoder recursion failure, and both wrappers' end-to-end publication paths. Ordinary text, line endings, result envelopes, cleanup, timeouts, child-process exit codes, and a following option after a missing sensitive-option value remain observable.

The exact pull-request head must additionally pass the complete central unit suite, 100% production statement and branch coverage for the changed surface, production docstring checks, Secret Scan, CodeQL, Semgrep, Python Security, Security Scan, OpenCode, Noema, CodeRabbit, independent current-head approval, and branch protection before merge.

## Modular boundary

`sandboxed_verify.py`, `sandboxed_web_e2e.py`, and `redact_sensitive_log.py` remain independently executable scripts and reusable Python modules. Product repositories consume the behavior through the organization control plane without copying repository-local redaction code. The wrappers preserve their existing CLI and machine-readable result contracts.

## Rollback

Rollback must restore every publication sink as one atomic change. Removing only command redaction, JSON traversal, depth limits, malformed-record handling, service-tail redaction, or result-envelope redaction would recreate a bypass around the remaining controls. Before rollback, operators must prove that no allowlisted credential can reach child output or command metadata and must retain equivalent focused regression evidence.

## APA 7 references

MITRE Corporation. (2026). *CWE-117: Improper output neutralization for logs* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/117.html

MITRE Corporation. (2026). *CWE-532: Insertion of sensitive information into log file* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/532.html

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

Python Software Foundation. (2026). *subprocess—Subprocess management* (Python 3.14.6 documentation). https://docs.python.org/3/library/subprocess.html
