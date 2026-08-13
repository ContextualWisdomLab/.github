# Sandbox command-metadata redaction

검토 기준일: **2026-08-13**

## Decision

`sandboxed_verify` and `sandboxed_web_e2e` redact subprocess stdout/stderr
and also the command argv, `backend_cmd` / `frontend_cmd` / `e2e_cmd`,
and `evidence_note` fields before they are printed or JSON-serialized.
Provider token shapes include GitHub PATs, Slack, AWS, OpenAI `sk-`, and
NVIDIA NIM `nvapi-` (the org `NVIDIA_NIM_API_KEY` form). Operational PII
is not masked. Materialize accepts only exact SHA-256 pins or a bounded
relative `-r` include; a lone `--require-hashes` line is not lock evidence.

CWE-532 forbids writing sensitive information to log files (MITRE, n.d.).
Command metadata is a log.

## References

MITRE. (n.d.). *CWE-532: Insertion of sensitive information into log file*.
Retrieved August 13, 2026, from
https://cwe.mitre.org/data/definitions/532.html
