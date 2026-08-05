# Sandboxed command and output redaction

## Decision

The central verification wrappers treat subprocess output, service log tails, command arguments, shell-command strings, and reviewer evidence notes as potentially sensitive before writing them to GitHub Actions logs or machine-readable review evidence.

One trusted redaction module owns this publication boundary:

- captured standard output and standard error are redacted before printing;
- `TimeoutExpired` byte and text payloads use the same redaction path;
- service log tails are redacted before publication;
- command arguments following sensitive options such as `--token`, `--password`, or `--api-key` are replaced;
- sensitive `KEY=value` command arguments are replaced while preserving the key;
- standalone provider-token shapes are removed;
- shell command strings are parsed without execution and reconstructed from redacted arguments; and
- JSON result markers redact commands and evidence notes before serialization.

The original argument vectors and output are used only inside the isolated execution boundary. Redaction changes neither the command that runs nor its exit status. It is applied at every publication sink instead of depending on each child process to avoid printing credentials.

## Threat model

Repository verification commands and web end-to-end services can emit credentials through exception messages, dependency-manager diagnostics, HTTP-client traces, command-line options, environment-derived configuration, startup logs, and timeout payloads. An explicitly allowlisted environment variable can therefore remain correctly scoped to a child process and still be disclosed when that child echoes it.

GitHub Actions logs and review envelopes are durable evidence with a potentially broader readership than the originating credential. MITRE classifies insertion of sensitive information into log files as CWE-532. OWASP's current logging guidance identifies access tokens, passwords, database connection strings, encryption keys, and other primary secrets as values that should normally be removed, masked, sanitized, hashed, or encrypted before logging. NIST SSDF requires protection of software and development artifacts from unauthorized access and disclosure.

## Security boundaries

- No provider-shaped credential literal is committed as a test fixture. Tests construct credential-shaped values from fragments at runtime so Secret Scan remains authoritative.
- Redaction is fail-closed for recognized sensitive option names, assignments, bearer/basic values, JWTs, and known provider token formats, but it is not a general data-loss-prevention engine.
- Sensitive option detection uses explicit credential terms. Ambiguous short flags such as `-p` are not guessed because they can mean port, path, project, or password depending on the child tool.
- Shell strings are tokenized with `shlex.split`; no shell is invoked for redaction. Malformed strings fall back to line-oriented redaction.
- `subprocess.run` and `subprocess.Popen` receive structured argument arrays with `shell=False`. Preventing shell interpretation and preventing log disclosure are independent controls.
- File paths, working directories, and sandbox paths remain visible operational evidence. Operators must not place credentials in path names.
- Redaction preserves line boundaries and ordinary non-sensitive diagnostics. It does not transform a failed command into a successful result or suppress a nonzero exit status.

No formal OWASP, NIST, or CWE conformity is claimed.

## Verification contract

The focused regression suite constructs a credential-shaped token at runtime and proves that it does not appear in:

1. completed verification stdout or stderr;
2. timeout output supplied as bytes or text;
3. human-readable command displays;
4. JSON result-marker command arrays;
5. backend, frontend, or E2E shell-command fields;
6. reviewer evidence notes; or
7. service log tails.

The tests also cover separate sensitive options, `--option=value`, `KEY=value` assignments, standalone provider-token shapes, malformed shell quoting, missing logs, bounded final-line selection, and both wrappers' end-to-end publication paths. Ordinary text, line endings, result envelopes, cleanup, timeouts, and child-process exit codes remain observable.

The exact pull-request head must additionally pass the complete central unit suite, 100% production statement and branch coverage for the changed surface, production docstring checks, Secret Scan, CodeQL, Semgrep, Python Security, Security Scan, OpenCode, Noema, CodeRabbit, independent current-head approval, and branch protection before merge.

## Modular boundary

`sandboxed_verify.py`, `sandboxed_web_e2e.py`, and `redact_sensitive_log.py` remain independently executable scripts and reusable Python modules. Product repositories consume the behavior through the organization control plane without copying repository-local redaction code. The wrappers preserve their existing CLI and machine-readable result contracts.

## Rollback

Rollback must restore every publication sink as one atomic change. Removing only command redaction, service-tail redaction, or result-envelope redaction would recreate a bypass around the remaining controls. Before rollback, operators must prove that no allowlisted credential can reach child output or command metadata and must retain equivalent focused regression evidence.

## APA 7 references

MITRE Corporation. (2026). *CWE-117: Improper output neutralization for logs* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/117.html

MITRE Corporation. (2026). *CWE-532: Insertion of sensitive information into log file* (CWE Version 4.20). https://cwe.mitre.org/data/definitions/532.html

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 5, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

Python Software Foundation. (2026). *subprocess—Subprocess management* (Python 3.14.6 documentation). https://docs.python.org/3/library/subprocess.html
