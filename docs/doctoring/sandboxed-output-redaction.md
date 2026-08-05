# Sandboxed subprocess output redaction

## Decision

The central verification wrappers treat subprocess output, service log tails,
command arguments, shell-command strings, and reviewer evidence notes as
potentially sensitive before writing them to GitHub Actions logs or machine-readable
review evidence.

One trusted redaction module now owns this boundary:

- captured standard output and standard error are redacted before printing;
- `TimeoutExpired` byte and text payloads use the same redaction path;
- service log tails are redacted before publication;
- command arguments following sensitive options such as `--token`,
  `--password`, or `--api-key` are replaced;
- sensitive `KEY=value` command arguments are replaced while preserving the key;
- shell command strings are parsed without execution and then reconstructed from
  redacted arguments; and
- JSON result markers redact commands and evidence notes before serialization.

The original command and output remain available only inside the isolated process
boundary for execution. Redaction is applied at every publication sink rather than
mutating the command that is executed.

## Threat model

Repository verification commands and web E2E services can emit credentials from:

- exception messages and stack traces;
- dependency-manager or HTTP-client diagnostics;
- command-line options;
- environment-derived configuration echoed by a child process;
- service startup logs; and
- timeout payloads returned as either bytes or text.

GitHub Actions logs are durable review artifacts. A credential exposed there may
be read by people, bots, log exporters, or downstream review tooling beyond the
process that originally possessed it. A forged or malformed log line can also
mislead automated diagnosis.

OWASP's current logging guidance says that access tokens, authentication
passwords, database connection strings, encryption keys, and other primary
secrets should normally be removed, masked, sanitized, hashed, or encrypted
rather than recorded directly. It also requires sanitization of untrusted event
data against CR, LF, and delimiter injection and warns that logging failures must
not permit information leakage. MITRE CWE-117 defines the corresponding weakness
as external input written to logs without correct neutralization and identifies
confidentiality, integrity, availability, and non-repudiation consequences.

## Security boundaries

- No provider-shaped credential literal is committed as a test fixture. Tests
  construct credential-shaped values at runtime so secret scanning remains
  authoritative.
- Redaction is fail-closed for recognized sensitive option names and credential
  formats, but it is not a general data-loss-prevention engine.
- Sensitive option detection is deliberately limited to explicit credential
  terms. Ambiguous short flags such as `-p` are not guessed because they can mean
  port, path, project, or password depending on the child tool.
- Shell strings are tokenized with `shlex.split`; no shell is invoked for
  redaction. Malformed strings fall back to the existing line-oriented redactor.
- `subprocess.run` and `subprocess.Popen` receive argument arrays with
  `shell=False`. This is independent of output redaction: preventing shell
  interpretation does not prevent a child process from printing a secret.
- File paths, working directories, and sandbox paths are preserved as operational
  evidence. Operators must not embed credentials in path names.

No formal OWASP, NIST, or CWE conformity is claimed.

## Verification contract

The focused regression suite constructs a credential-shaped token at runtime and
proves that it does not appear in:

- completed verification stdout or stderr;
- timeout output supplied as bytes or text;
- command displays;
- JSON result-marker command arrays;
- backend, frontend, or E2E shell-command fields;
- evidence notes; or
- service log tails.

The tests also cover separate sensitive options, `KEY=value` assignments,
standalone provider-token shapes, malformed shell quoting, missing logs, bounded
log tails, and both verification wrappers' end-to-end publication paths.

The exact pull-request head must additionally pass the complete unit suite,
statement and branch coverage, production docstring checks, Secret Scan,
CodeQL, Semgrep, Python Security, and independent current-head review before
merge.

## References

MITRE Corporation. (2026). *CWE-117: Improper output neutralization for logs*
(CWE Version 4.20). https://cwe.mitre.org/data/definitions/117.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the risk
of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series.
Retrieved August 5, 2026, from
https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
