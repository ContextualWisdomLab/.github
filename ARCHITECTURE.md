# Architecture — ContextualWisdomLab `.github`

This repository is the organization control plane. It is not naruon and it
does not own product data. Sibling products remain standalone modules; this
repo publishes org profile assets, reusable required workflows, and the
review/merge schedulers those products consume.

## System context

```mermaid
flowchart LR
  Buyer["Commercial buyer / reviewer"]
  Agents["Agents on AGENTS.md"]
  Project["GitHub Project #1"]
  Hub["This repo: org .github"]
  Products["Owned products<br/>naruon · orchestrator · engines"]
  Runner["Required workflows in each repo context"]

  Buyer --> Hub
  Agents --> Project
  Agents --> Hub
  Project --> Hub
  Hub --> Runner
  Runner --> Products
  Products -->|"standalone or as module"| Buyer
```

## Incomplete-retry severity gate

```mermaid
flowchart TD
  Log["Strix console tee"]
  Gate{"Trusted gate printed incomplete log-only verdict?"}
  Finding{"Accepted finding without that verdict?"}
  Neutral["Backend-unavailable skip"]
  Fail["Fail closed"]

  Log --> Gate
  Gate -->|"yes, leftover TUI only"| Neutral
  Gate -->|"no"| Finding
  Finding -->|"yes"| Fail
  Finding -->|"no"| Neutral
```

CWE-754: leftover `Severity:` TUI lines are not accepted findings.
Public scans bind `NVIDIA_NIM_API_KEY`. Vulnerability reports are never
neutralized.

## Control-plane data flow

```mermaid
sequenceDiagram
  participant PR as Pull request
  participant RW as Required workflows
  participant OC as OpenCode reviewer
  participant SV as sandboxed_verify / web E2E
  participant MS as Merge scheduler

  PR->>RW: pull_request_target on trusted base
  RW->>OC: bounded evidence + NVIDIA NIM / OpenCode
  OC->>SV: PoC command in isolated copy
  SV-->>OC: redacted stdout/stderr + command metadata
  OC-->>PR: APPROVE or request changes
  MS->>PR: merge only on current-head approval + green checks
```

## Trust boundaries

- Required review workflows execute **base-branch** scripts.
- Reviewer agents stay `edit: deny`.
- Logs redact credential shapes. They do not mask operational PII.
- LLM and scheduled agents bind `NVIDIA_NIM_API_KEY`. They never use
  `COPILOT_GITHUB_TOKEN`.
- Rust remains the psychometric arithmetic owner.

## Quality gates

`scripts/ci/` ships with 100% statement/branch coverage and 100%
docstrings.

## Related durable documents

- [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md)
- [`PR_GOVERNANCE_AUDIT.md`](PR_GOVERNANCE_AUDIT.md)
- [`docs/doctoring/strix-incomplete-retry-severity.md`](docs/doctoring/strix-incomplete-retry-severity.md)
