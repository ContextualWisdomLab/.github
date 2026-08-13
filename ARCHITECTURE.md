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

## Line-anchored REQUEST_CHANGES

```mermaid
flowchart TD
  Finding["REQUEST_CHANGES finding"]
  Path{"Exact current-head changed file?"}
  Line{"Line exists in current-head blob?"}
  Inline["Publish GitHub inline comment"]
  Body["Keep the remark in the review body"]

  Finding --> Path
  Path -->|"no"| Body
  Path -->|"yes"| Line
  Line -->|"no"| Body
  Line -->|"yes"| Inline
```

CWE-1288: path and line must be consistent with the trusted current-head
artifact. Line `0` and `True` are not anchors (`0 > line_count` is
false). Reviewers stay `edit: deny`.

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
- [`docs/doctoring/review-line-anchored-findings.md`](docs/doctoring/review-line-anchored-findings.md)
