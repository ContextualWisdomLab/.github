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

## OSV pin and Scorecard token path

```mermaid
sequenceDiagram
  participant Dep as Dependabot SHA bump
  participant Scan as security-scan.yml
  participant Score as OpenSSF Scorecard
  participant Buyer as Security dashboard

  Dep->>Scan: pin osv-scanner-action@SHA
  Note over Scan: comment must name the embedded release
  alt one-shot writer with contents write
    Scan->>Score: Token-Permissions score 0
    Score-->>Buyer: failed check
  else in-tree comment correction, no write token
    Scan->>Score: no extra write permission
    Score-->>Buyer: scanner release is auditable
  end
```

## Trust boundaries

- Required review workflows execute **base-branch** scripts. A PR that edits
  those workflows cannot widen its own `pull_request_target` token.
- Reviewer agents stay `edit: deny`. They judge; they do not implement.
- One-shot repair workflows must not set top-level `contents: write` to
  rewrite comments. Scorecard Token-Permissions treats that as score 0.
- OSV `uses:` comments must name the release the pinned SHA embeds. A
  stale `# v2.3.8` on a v2.5.0 SHA is an audit-trail defect.
- Logs and review receipts redact credentials. They do not mask
  operational PII that the control plane must process.
- LLM and scheduled agents bind `NVIDIA_NIM_API_KEY` (env may be
  `NVIDIA_API_KEY`). They never use `COPILOT_GITHUB_TOKEN`. Existing
  review-agent key schemes stay unchanged.

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
- [`docs/scorecard-governance.md`](docs/scorecard-governance.md) —
  Scorecard Token-Permissions and other check IDs.
- [`docs/doctoring/osv-scanner-version-comment-scorecard.md`](docs/doctoring/osv-scanner-version-comment-scorecard.md)
  — OSV version-comment honesty (APA 7th).
