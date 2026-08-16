# Sandbox subprocess evidence redaction

## Incident boundary

The organization sandbox wrappers already removed ambient secret-bearing environment variables before launching pull-request verification commands. That control did not cover a different disclosure path: child processes and long-running services can emit credential-shaped values to stdout, stderr, timeout evidence, or service log files. `sandboxed_verify.py` and `sandboxed_web_e2e.py` forwarded those captured values into GitHub Actions/review evidence without passing them through the existing `redact_sensitive_log.redact_text` boundary.

This is an evidence-handling defect. It is not a shell-injection defect, a reason to change subprocess argv/process-group semantics, a provider-routing problem, or a reason to broaden/revoke repository credentials.

## RCA

The causal chain is:

1. a verification command or local web service emits text controlled by the repository-under-review;
2. the sandbox correctly captures that text through `subprocess.PIPE`, `TimeoutExpired`, or a service log file;
3. the wrapper prints the captured text into CI/review evidence;
4. the mature central log redactor was not invoked on this output boundary; and
5. therefore a token/password/session-key-shaped value can cross the sandbox boundary even though the corresponding ambient environment variable was scrubbed.

Python documents `subprocess.run(..., shell=False, stdout=PIPE, stderr=PIPE, timeout=...)` and `TimeoutExpired` as normal captured-output mechanisms. The repair therefore leaves process execution semantics unchanged and treats the captured text as untrusted evidence that requires redaction before publication.

## Feasibility analysis

The following candidates were evaluated:

- **Change or remove subprocess execution. Rejected.** The defect occurs after capture, so changing argv, shell mode, process groups, or timeouts would not address the disclosure mechanism and would add unrelated behavioral risk.
- **Rely only on GitHub Actions secret masking. Rejected.** GitHub recommends masking sensitive values and notes that log redaction is not a complete substitute for avoiding sensitive output; child output may contain transformed or non-registered sensitive data. Repository-under-review output must therefore cross the product's own deterministic redaction boundary.
- **Import the mixed sentinel #841. Rejected.** That branch combined this defect with unrelated readiness-URL hardening, production changes preceded its tests, and the external writer reported that its narrowed result could not be published. Rewriting or manually reconstructing unpublished UI state would weaken provenance.
- **Apply the existing redactor at the evidence-output boundary. Accepted.** This is the smallest reversible change, requires no new credential or permission, preserves process semantics, and is directly testable with credential-shaped fixtures.

The first GREEN implementation exposed five narrower defects in that shared boundary during an exhaustive diff review:

- valid JSON took a structured branch that redacted only sensitive key names and never scanned string values under opaque keys;
- substring key matching hid benign diagnostics such as `token_count` and `password_policy`;
- terminal ANSI sequences could split a sensitive key or provider-token signature before detection;
- explicitly allowed environment values were not supplied to the redactor, so an opaque value printed without a recognizable key or provider prefix survived; and
- `_redact_assignments()` restarted a suffix scan at every character in a long key-like line, producing observed quadratic growth even though its contract claimed linear parsing.

The root cause was not missing calls in the two wrappers anymore. It was an incomplete normalization and value-provenance contract in the shared redactor, plus repeated suffix scanning. The follow-up repair canonicalizes terminal evidence before matching, recursively scans JSON keys and string values, classifies credential fields by semantic words while exempting explicit diagnostic-metadata endings, passes explicitly allowed environment values through a validated literal-sensitive path, and advances the assignment parser by complete key spans.

A consumer-path review then found additional integration hazards: post-processing the prefixed result marker could corrupt otherwise valid JSON, selecting a service tail before literal redaction could expose a clipped multiline value, a permissive three-segment pattern hid the `api.deepseek.com` failure signal as if it were a JWT, excessive valid JSON nesting could abort the central failed-check collector, literal values such as `true` could corrupt JSON types, terminal overwrite/format controls could reconstruct rendered secrets, separated CLI options could leave their following credential visible, and setup, launch, or cleanup exceptions could escape the boundary. The bounded repair now redacts trusted result schemas before serialization, protects existing markers with a single-pass matcher, redacts complete service logs before tail selection, verifies decoded JOSE headers, preserves JSON scalar types and every supported line separator, handles separated credential options, fails closed across multiline or unterminated terminal controls, falls back safely on excessive JSON recursion, and captures explicitly allowed values before fallible setup. It does not implement the separate output-memory and service-file quotas tracked by #766.

Issue #907 then exposed a distinct argv-evidence boundary: direct Docker/Podman login options were protected, but opaque credentials inside supported `env` split-string and shell `-c` operands were still treated as ordinary data. The repair recognizes only exact `env -S`, `env --split-string`, `env --split-string=...`, and exact `sh`/`bash`/`dash`/`ksh`/`zsh` basenames with an exact or combined `-c` selector. One root-owned context compiles caller literals once and shares limits of 65,536 UTF-8 input bytes, 4,096 parsed tokens, 262,144 cumulative scan bytes, and four wrapper levels. Unsupported quoting, expansion, comments, escapes, compound-shell syntax, ambiguous trailing argv, or exhausted root budgets fail closed; the depth boundary replaces the remaining nested operand rather than scanning it again. The command is never executed or rewritten at its execution boundary.

The same repair fixes option-context false positives: only an exact Docker/Podman `login` subcommand gives `-p` password meaning; Docker publish ports, SSH ports, unrelated `login` arguments, GNU env unset/chdir operands, and the registry after valid `--password-stdin` remain visible. The invalid `--password-stdin=...` spelling remains conservatively redacted. Output/service-file memory quotas remain separate Issue #766.

Issue #908 then exposed an ordering and representation defect in the raw-text path. Splitting evidence into lines before structural handling loses the association between a multiline sensitive key, colon, and value. Parsing a complete document into a Python dictionary would avoid that split but collapse duplicate members and normalize whitespace, escapes, number spelling, and punctuation. RFC 8259 §4 says object member names SHOULD be unique and that the behavior of software that receives duplicate names is unpredictable: some keep the last pair, some error, and some preserve every pair (Bray, 2017). ECMA-404 and ISO/IEC 21778 impose no uniqueness or order restriction; those are processor semantics (Ecma International, 2017; International Organization for Standardization, 2017). The repair therefore recognizes complete JSON and JSON spans before line splitting with an iterative token/span state machine. It decodes only bounded key and string tokens for classification, retains every untouched source slice, and applies non-overlapping scalar/key span replacements afterward. Duplicate members retain order and count so a later parser cannot reconstruct a secret from a discarded first pair; sensitive arrays and objects retain shape while scalar leaves keep their string, integer, floating-point, boolean, or null category.

The raw parser shares one root budget of 65,536 input bytes, depth 64, 8,192 tokens, 32,768 bytes per string token, 2,048 replacements, and 262,144 cumulative work units. Limit exhaustion and malformed structural evidence with a sensitive key fail closed to one stable marker without exception text. A failed opener is charged only against the window until the next plausible JSON start, so GitHub Actions `##[group]` markers and prose `[timeout]` brackets cannot erase a later complete object. Downloaded job logs still prefix every line with an RFC 3339 UTC timestamp of the form `YYYY-MM-DDTHH:MM:SS.nnnnnnnZ ` before the payload (GitHub, n.d.-a; Klyne & Newman, 2002). Treating that prefix as JSON text made `{` after the timestamp space a plausible opener, then the next timestamp broke the parse and `_looks_like_sensitive_json_candidate` fail-closed the entire log. The parser now skips line-start runner timestamps the same way it skips JSON whitespace and maps replacements onto the original source, so a pretty-printed password object remains one span. RFC 8259 §2 `begin-array` allows only a value or `]` after optional whitespace (Bray, 2017). A `[` therefore opens a span only when the next significant token is `true`, `false`, `null`, a number, a string, a container, or `]`; line-start `[INFO]` / `[timeout]` labels stay in the unstructured gap. Command strings and argv arrays reuse the bounded wrapper redactor; when its fail-closed representation changes argv length, the JSON path preserves array shape by replacing every original element. Complete valid spans can coexist with prefixes, suffixes, and multiple records. This does not change `redact_json_value()` for already-materialized trusted objects and does not claim Issue #766's output-memory closure.

## Test-first evidence

A clean branch was created from protected `main` `6eb06cdd08c79a06f7b390069d4ffa49e2eb7dba`.

The first commit `f33b37d882ddb8ab0ef8ffd4e843cb5edce9adc9` changed only `tests/test_sandboxed_log_redaction_regression.py`. Hosted exact-head quality run `31291746435`, job `93190018774`, then produced the intended RED result: **4 failed, 23 passed**. Each new failure exposed credential-shaped text crossing one of the required output boundaries.

Only after that hosted RED evidence did production change. The implementation:

- redacts completed `sandboxed_verify` stdout/stderr;
- decodes and redacts `sandboxed_verify` timeout stdout/stderr, including byte-valued `TimeoutExpired` evidence;
- redacts completed web-E2E stdout/stderr;
- reuses the redacted timeout helper for web-E2E timeout evidence; and
- redacts complete backend/frontend service-log text before selecting and printing the bounded tail.

Normal child-command exit codes, readiness URL, redirect, executed subprocess argv, process-group, timeout, provider/model, workflow permission, and branch-protection behavior are unchanged. Workspace-setup and process-launch exceptions now return fail-closed code `126` with a redacted diagnostic instead of propagating a raw traceback. A non-empty explicitly allowed environment value shorter than eight characters, or one identical to fixed evidence text that must remain machine-readable, also returns `126` before child execution because it cannot be redacted unambiguously. Other values, including whitespace-bearing credentials, are passed to the child unchanged while their raw and escaped evidence representations are suppressed.

Exact-head focused acceptance on `9dd2ab31a8eab9ef7b4572e37c68023df6a0f16e` reports **32 passed** and exact **100% statement and branch coverage** for both owned production modules (`265` statements and `82` branches total). The permanent quality workflow also enforces public callable docstrings, exact-head checkout, a complete repository suite, the central Strix quick gate, compilation, and a clean worktree before Ready status is permitted.

The follow-up fail-first contract independently reproduced eight initial failures: opaque JSON values, benign JSON metadata over-redaction, ANSI-split evidence, quadratic long-line processing, and opaque `--allow-env` values across completed/timeout verification plus completed/timeout/service-tail E2E paths. Consumer review added fail-first cases for marker integrity, truncation order, credential-bearing JSON keys, joined and suffixed credential fields, authorization headers, URL userinfo, private-key blocks, raw and escaped explicit values, all supported line separators, JSON scalar types, diagnostic domains, pathological JSON depth, high line/value counts, separated credential options, short or fixed-evidence-colliding allowed values, terminal overwrite and multiline/unterminated control sequences, and pre-copy/backend/frontend/E2E launch and cleanup exceptions. After the bounded repair, the focused suite reports **102 passed** and exact **100% statement and branch coverage** across `redact_sensitive_log.py`, `sandboxed_verify.py`, and `sandboxed_web_e2e.py` (`605` statements and `206` branches). The exact-head quality workflow now owns all three modules and the shared redactor security tests, so a wrapper-only coverage result cannot promote a redactor regression.

The wrapper follow-up began with **31 focused failures** covering both GNU env split spellings, all five supported shells, combined `-c` selectors, env-to-shell nesting, malformed/compound operands, trailing positional ambiguity, resource limits, depth, and option false positives. The bounded implementation reports **142 passed** in the permanent focused quality selection with exact **100% statement and branch coverage** across the three owned modules (`784` statements and `302` branches), followed by **1,060 passed plus 16 subtests** and exact complete owned-production coverage (`7,395` statements and `2,960` branches) in the complete repository suite and a passing Strix quick gate. Fixtures construct opaque credentials at runtime.

The atomic JSON follow-up began on exact parent `18a6d125fead8cb95972fe3e1a97e4cc4163e9d2` with a test-only head that produced the intended local RED result: **5 failed, 1 passed**. The failures reproduced multiline separation, duplicate-key loss, scalar/container normalization, mixed-record handling, and malformed-candidate leakage before production changed. The GREEN boundary reports **155 focused tests passed** with exact **100% statement and branch coverage** across the three owned modules (`1,039` statements and `416` branches). A later exact-head follow-up added a realistic Actions `##[group]` pretty-printed password dump and a prose `[timeout]` control; both now keep diagnostic text and rewrite only credential leaves. After that follow-up the focused selection reports **163 passed** with exact **100% statement and branch coverage** (`1,064` statements and `426` branches). A successor then failed first on a per-line-timestamped downloaded job log and a line-start `[INFO]` diagnostic that named `"password":`; both previously collapsed the entire buffer to `[REDACTED]`. After skipping runner timestamps inside spans and requiring a JSON value after `[`, those fixtures keep group/status text and rewrite only credential leaves. The focused selection now reports **168 passed** with exact **100% statement and branch coverage** across the three owned modules (`1,094` statements and `444` branches). Additional fixtures exercise escaped spelling, empty containers, iterative depth, token, byte, string and replacement exhaustion, malformed parser states, shape-preserving command fallback, benign oversized input, trusted materialized-object collision handling, CRLF timestamps, and literal `[true]` / `[false]` / `[null]` / `[]` arrays without committing a fixed credential-shaped literal.

## Security and privacy interpretation

Redaction is defense in depth, not authorization. It does not make arbitrary sensitive material safe to publish and it does not authorize repositories to pass secrets into sandbox commands. The existing environment minimization remains the primary ingress control; deterministic output redaction limits accidental disclosure if a child process or service emits sensitive-looking evidence anyway.

ANSI styling canonicalization preserves visible diagnostic text and line separators, while cursor movement, backspace, multiline/unterminated control payloads, and invisible Unicode format controls fail closed for every affected evidence line or value. Structured JSON retains benign failure, policy, count, status, expiry, type, and usage metadata, while credential-denoting keys, credential material used as a key, credential-shaped string values, authorization headers, URL userinfo, and multiline private-key blocks are replaced without changing boolean or numeric types. Result markers remain one-line valid JSON with stable trusted keys after redaction, and the collector's literal `api.deepseek.com` classification signal remains visible. Literal protection is limited to non-empty values of names explicitly passed through `--allow-env`; values shorter than eight characters or colliding with fixed evidence text are rejected before execution, while whitespace-bearing values remain supported. The ordinary safe environment allowlist is not treated as secret, avoiding blanket removal of paths, locale data, or other useful diagnostics.

Raw JSON layout preservation applies before line-oriented normalization. It does not interpret arbitrary prefixes as trusted JSON, publish parser errors, reconstruct a dictionary, or silently accept a partially parsed sensitive candidate. Existing escape spelling and line endings are therefore diagnostic evidence rather than data to canonicalize. A bounded benign non-JSON or malformed fragment still uses the general redactor; a fragment that establishes a sensitive structural key but cannot establish a safe value boundary fails closed.

The redactor operates on CI-facing text only. It does not mutate files in the copied repository, service log files on disk, subprocess input, or successful child-process status and lifetime. The wrappers separately apply the documented pre-execution and exception code `126` policy. Operators should therefore interpret `[REDACTED]` as evidence suppression, not as successful removal of sensitive data from the source system that produced it.

## Rollback

If the redaction integration causes a demonstrated diagnostic incompatibility, revert the production redaction commits while retaining the fail-first regression and this doctoring record. Do not disable the regression, weaken the credential-shaped fixtures, or replace the deterministic boundary with blanket omission of all stdout/stderr. A rollback is incomplete until the resulting protected-main behavior is reassessed for disclosure risk.

## Operational acceptance

PR checks prove the code path, not protected-main operation. After protected integration, run one bounded sandbox verification fixture that emits synthetic credential-shaped stdout/stderr and one bounded web-E2E fixture that emits a synthetic service-log credential. Accept the repair only if protected-main workflow evidence shows the synthetic value absent, `[REDACTED]` present, ordinary diagnostic text preserved, and the expected exit code/process cleanup behavior unchanged.

## References

Bray, T. (Ed.). (2017). *The JavaScript Object Notation (JSON) data interchange format* (RFC 8259). Internet Engineering Task Force. https://doi.org/10.17487/RFC8259

Ecma International. (2017). *The JSON data interchange syntax* (Standard ECMA-404, 2nd ed.). https://ecma-international.org/publications-and-standards/standards/ecma-404/

GitHub. (n.d.-a). *Using workflow run logs*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs

GitHub. (n.d.-b). *Secure use reference*. GitHub Docs. Retrieved August 9, 2026, from https://docs.github.com/en/actions/reference/security/secure-use

GitHub. (n.d.-c). *Using secrets in GitHub Actions*. GitHub Docs. Retrieved August 9, 2026, from https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

International Organization for Standardization. (2017). *Information technology — The JSON data interchange syntax* (ISO/IEC 21778:2017). https://www.iso.org/standard/71616.html

Klyne, G., & Newman, C. (2002). *Date and time on the Internet: Timestamps* (RFC 3339). Internet Engineering Task Force. https://doi.org/10.17487/RFC3339

MITRE Corporation. (n.d.). *CWE-180: Incorrect behavior order: Validate before canonicalize*. CWE. Retrieved August 9, 2026, from https://cwe.mitre.org/data/definitions/180.html

MITRE Corporation. (n.d.). *CWE-407: Inefficient algorithmic complexity*. CWE. Retrieved August 9, 2026, from https://cwe.mitre.org/data/definitions/407.html

MITRE Corporation. (n.d.). *CWE-532: Insertion of sensitive information into log file*. CWE. Retrieved August 9, 2026, from https://cwe.mitre.org/data/definitions/532.html

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

OWASP Foundation. (n.d.). *Logging cheat sheet*. OWASP Cheat Sheet Series. Retrieved August 9, 2026, from https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html

Python Software Foundation. (2026). *subprocess — Subprocess management* (Python 3.14.6 documentation). https://docs.python.org/3.14/library/subprocess.html
