# Architecture — ContextualWisdomLab `.github`

This repository is the organization control plane. Sibling products remain
standalone modules.

## Sandbox command-metadata redaction

```mermaid
flowchart TD
  Cmd["verify / web E2E command argv"]
  Redact["redact_text including nvapi-"]
  Log["stdout / result JSON"]

  Cmd --> Redact --> Log
```

Operational PII is not masked. Credentials stay redacted.

## Related

- [`docs/doctoring/sandbox-command-metadata-redaction.md`](docs/doctoring/sandbox-command-metadata-redaction.md)
