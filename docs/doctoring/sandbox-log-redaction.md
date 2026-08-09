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

## Test-first evidence

A clean branch was created from protected `main` `6eb06cdd08c79a06f7b390069d4ffa49e2eb7dba`.

The first commit `f33b37d882ddb8ab0ef8ffd4e843cb5edce9adc9` changed only `tests/test_sandboxed_log_redaction_regression.py`. Hosted exact-head quality run `31291746435`, job `93190018774`, then produced the intended RED result: **4 failed, 23 passed**. Each new failure exposed credential-shaped text crossing one of the required output boundaries.

Only after that hosted RED evidence did production change. The implementation:

- redacts completed `sandboxed_verify` stdout/stderr;
- decodes and redacts `sandboxed_verify` timeout stdout/stderr, including byte-valued `TimeoutExpired` evidence;
- redacts completed web-E2E stdout/stderr;
- reuses the redacted timeout helper for web-E2E timeout evidence; and
- redacts the bounded backend/frontend service log tail before it is printed.

No readiness URL, redirect, subprocess argv, process-group, timeout, provider/model, credential, workflow permission, or branch-protection behavior is changed by the production repair.

Exact-head focused acceptance on `9dd2ab31a8eab9ef7b4572e37c68023df6a0f16e` reports **32 passed** and exact **100% statement and branch coverage** for both owned production modules (`265` statements and `82` branches total). The permanent quality workflow also enforces public callable docstrings, exact-head checkout, a complete repository suite, the central Strix quick gate, compilation, and a clean worktree before Ready status is permitted.

## Security and privacy interpretation

Redaction is defense in depth, not authorization. It does not make arbitrary sensitive material safe to publish and it does not authorize repositories to pass secrets into sandbox commands. The existing environment minimization remains the primary ingress control; deterministic output redaction limits accidental disclosure if a child process or service emits sensitive-looking evidence anyway.

The redactor operates on CI-facing text only. It does not mutate files in the copied repository, service log files on disk, subprocess input, exit status, timing, or process lifetime. Operators should therefore interpret `[REDACTED]` as evidence suppression, not as successful removal of sensitive data from the source system that produced it.

## Rollback

If the redaction integration causes a demonstrated diagnostic incompatibility, revert the production redaction commits while retaining the fail-first regression and this doctoring record. Do not disable the regression, weaken the credential-shaped fixtures, or replace the deterministic boundary with blanket omission of all stdout/stderr. A rollback is incomplete until the resulting protected-main behavior is reassessed for disclosure risk.

## Operational acceptance

PR checks prove the code path, not protected-main operation. After protected integration, run one bounded sandbox verification fixture that emits synthetic credential-shaped stdout/stderr and one bounded web-E2E fixture that emits a synthetic service-log credential. Accept the repair only if protected-main workflow evidence shows the synthetic value absent, `[REDACTED]` present, ordinary diagnostic text preserved, and the expected exit code/process cleanup behavior unchanged.

## References

GitHub. (n.d.). *Secure use reference*. GitHub Docs. Retrieved August 9, 2026, from https://docs.github.com/en/actions/reference/security/secure-use

GitHub. (n.d.). *Using secrets in GitHub Actions*. GitHub Docs. Retrieved August 9, 2026, from https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets

Python Software Foundation. (2026). *subprocess — Subprocess management* (Python 3.14.6 documentation). https://docs.python.org/3.14/library/subprocess.html
