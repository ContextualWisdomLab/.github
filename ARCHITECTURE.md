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

## Hourly commercial-readiness coordinator

```mermaid
flowchart TD
  Tick["Scheduled minute-7 tick"]
  Org{"organization == ContextualWisdomLab?"}
  Lease["Paginated writer-lease inventory"]
  Snap["Refetch default SHA, workflows, runs, PRs"]
  Plan["At most one review-repair and one product dispatch"]
  Token["PR_REVIEW_MERGE_TOKEN only at dispatch"]
  Fail["Fail closed; receipt is not merge evidence"]

  Tick --> Org
  Org -->|"no"| Fail
  Org -->|"yes"| Lease
  Lease --> Snap
  Snap -->|"writer appeared or state moved"| Fail
  Snap -->|"stable"| Plan
  Plan --> Token
```

The 15-minute merge scheduler remains the only merge engine. This hourly
coordinator never approves, merges, or interprets a failed check as success.

## Control-plane data flow

```mermaid
sequenceDiagram
  participant PR as Pull request
  participant RW as Required workflows
  participant OC as OpenCode reviewer
  participant SV as sandboxed_verify / web E2E
  participant MS as Merge scheduler
  participant CR as Hourly readiness coordinator

  PR->>RW: pull_request_target on trusted base
  RW->>OC: bounded evidence + NVIDIA NIM / OpenCode
  OC->>SV: PoC command in isolated copy
  SV-->>OC: redacted stdout/stderr + command metadata
  OC-->>PR: APPROVE or request changes
  MS->>PR: merge only on current-head approval + green checks
  CR->>MS: at most one review-repair dispatch after live refetch
```

## Trust boundaries

- Required review workflows execute **base-branch** scripts. A PR that edits
  those workflows cannot widen its own `pull_request_target` token.
- Reviewer agents stay `edit: deny`. They judge; they do not implement.
- Sandbox helpers copy the workspace, drop secret environment values unless
  explicitly allowlisted by **name**, and run subprocesses with `shell=False`.
- Logs and review receipts redact credential shapes (tokens, bearer values,
  known provider prefixes). They do not mask operational PII that the
  control plane must process.
- LLM and scheduled agents bind `NVIDIA_NIM_API_KEY` (env may be
  `NVIDIA_API_KEY`). They never use `COPILOT_GITHUB_TOKEN`. Existing
  review-agent key schemes stay unchanged.
- The hourly coordinator rejects any organization other than
  ContextualWisdomLab and never accepts `GITHUB_TOKEN` as a fleet writer.

## Quality gates

`scripts/ci/` ships with 100% statement/branch coverage and 100% docstrings.
CI installs Python tools only with `pip install --require-hashes`. Contract
tests pin workflow structure and governance prose so drift fails closed.

## Related durable documents

- [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) — mission and
  ecosystem.
- [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md)
  — Project #1 operation.
- [`PR_GOVERNANCE_AUDIT.md`](PR_GOVERNANCE_AUDIT.md) — live review/merge
  contract.
- [`docs/doctoring/organization-commercial-readiness-loop.md`](docs/doctoring/organization-commercial-readiness-loop.md)
  — current increment's coordinator decision and APA 7th citations.
