# Sandbox command-metadata secret redaction

## Incident and buyer impact

Review evidence helpers `scripts/ci/sandboxed_verify.py` and
`scripts/ci/sandboxed_web_e2e.py` already scrubbed subprocess stdout, stderr,
timeout streams, and service log tails. Command argv, backend/frontend/E2E
command strings, and reviewer `evidence_note` fields were still serialized as
raw text in CI logs. A commercial buyer inspecting GitHub Actions logs — or a
low-privilege collaborator reading a failed review receipt — could recover a
GitHub PAT, Slack bot token, or bearer credential that a test command had
passed as an argument. That is CWE-532 (insertion of sensitive information
into a log file), not a reason to mask operational names, paths, or pytest
selectors.

## Decision

Keep one redaction boundary: `redact_text` from
`scripts/ci/redact_sensitive_log.py`. Apply it to:

- the human-readable `sandboxed-verify: command=...` line;
- every argv fragment and `evidence_note` written by `emit_result`;
- `backend_cmd`, `frontend_cmd`, `e2e_cmd`, and `evidence_note` in the web
  E2E receipt.

Operational metadata stays visible. Only credential-shaped values and
token/secret/password assignments become `[REDACTED]`. This is secret
redaction under access control and audit. It is not operational-PII masking.
CSAP and SOC 2 CC6.1 / CC7.2 remain design constraints: credentials never
appear in review evidence; command structure that a reviewer must judge
remains readable.

## Test-first evidence

`tests/test_sandboxed_verify.py` and `tests/test_sandboxed_web_e2e.py` feed
real GitHub PAT (`ghp_`) and Slack bot (`xoxb-`) shapes through the shipped
`main()` / `emit_result()` functions and require those literals to be absent
from stdout, stderr, and the machine-readable result JSON while pytest
selectors and uvicorn/playwright command verbs remain.

## References

MITRE. (n.d.). *CWE-532: Insertion of sensitive information into log file*.
https://cwe.mitre.org/data/definitions/532.html

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

OWASP Foundation. (2025). *Logging cheat sheet*.
https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
