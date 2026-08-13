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

## OriginWeave hourly caller

`originweave-hourly-review-repair.yml` is a thin, read-only caller at minute
10. It names `ContextualWisdomLab/OriginWeave` and protected `main`, maps
only established scheduler credentials, and grants job-scoped
`id-token: write`. The reusable engine stays product-neutral.

## nonnest2 hourly caller

`nonnest2-hourly-review-repair.yml` is a thin, read-only caller at minute
16. It names `ContextualWisdomLab/nonnest2` and protected `master`, maps
only established scheduler credentials, and grants job-scoped
`id-token: write`. The reusable engine stays product-neutral.

## Hourly NVIDIA NIM repair gate

```mermaid
flowchart TD
  Hour["Hourly product caller"]
  Sched["Central reusable scheduler"]
  Bind{"Exact-head, same-repo, writer authority, sealed paths?"}
  Worker["repository_dispatch worker at github.sha"]
  NIM["NVIDIA NIM repair model"]
  Recheck{"Post-edit exact-head revalidation?"}
  Push["Push same-repository head"]
  Hold["Leave the tree unchanged"]

  Hour --> Sched
  Sched --> Bind
  Bind -->|"no"| Hold
  Bind -->|"yes"| Worker
  Worker --> NIM
  NIM --> Recheck
  Recheck -->|"no"| Hold
  Recheck -->|"yes"| Push
```

The worker checks out helpers at `${{ github.sha }}` so a later default-branch
push cannot replace privileged scripts after dispatch (CWE-367). Repair binds
`NVIDIA_NIM_API_KEY`, never `COPILOT_GITHUB_TOKEN`.

Product callers stagger Clearfolio at minute 23, DiskSage at minute 37, and
fast-mlsirm at minute 49. Each caller is read-only, dispatches at most one
repair, and delegates all privileged logic to the same sealed scheduler.

## Empirical review-quality gate

```mermaid
flowchart TD
  Pilot["Lifecycle-yield pilot"]
  Gold{"n >= 50 head-matched PRs and gold findings?"}
  Wilson["Wilson 95% CI vs CodeRabbit"]
  Shadow["Shadow mode; not a merge gate"]
  Insufficient["INSUFFICIENT_EVIDENCE"]

  Pilot --> Gold
  Gold -->|"no"| Insufficient
  Gold -->|"yes"| Wilson
  Wilson --> Shadow
```

Coverage-check failures stay merge-readiness evidence. They are not
source-defect labels and cannot prove commercial parity.

## Control-plane data flow

```mermaid
sequenceDiagram
  participant PR as Pull request
  participant RW as Required workflows
  participant OC as OpenCode reviewer
  participant SV as sandboxed_verify / web E2E
  participant QG as Quality scorer
  participant MS as Merge scheduler

  PR->>RW: pull_request_target on trusted base
  RW->>OC: bounded evidence + NVIDIA NIM / OpenCode
  OC->>SV: PoC command in isolated copy
  SV-->>OC: redacted stdout/stderr + command metadata
  OC-->>PR: APPROVE or request changes
  QG->>QG: confined paths; INSUFFICIENT_EVIDENCE until gold n
  MS->>PR: merge only on current-head approval + green checks
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
- Rust remains the psychometric arithmetic owner. Repair never substitutes
  Python for scoring math.
- The quality scorer reads only confined path roots and never executes
  model-proposed commands.
- The quality scorer reads only confined path roots and never executes
  model-proposed commands.

## Quality gates

`scripts/ci/` ships with 100% statement/branch coverage and 100% docstrings.
CI installs Python tools only with `pip install --require-hashes`. Contract
tests pin workflow structure and governance prose so drift fails closed. The
trusted `uv` exporter is downloaded from the literal GitHub Releases URL for
`uv` 0.12.1; `releases.astral.sh` is not the network sink.
tests pin workflow structure and governance prose so drift fails closed.

## Related durable documents

- [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) — mission and
  ecosystem.
- [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md)
  — Project #1 operation.
- [`PR_GOVERNANCE_AUDIT.md`](PR_GOVERNANCE_AUDIT.md) — live review/merge
  contract.
- [`docs/doctoring/hourly-nvidia-nim-autofix.md`](docs/doctoring/hourly-nvidia-nim-autofix.md)
  — current increment's repair-worker decision and APA 7th citations.
- [`docs/doctoring/fast-mlsirm-hourly-review-caller.md`](docs/doctoring/fast-mlsirm-hourly-review-caller.md)
  — product-specific psychometric repair heartbeat and scientific gates.
- [`docs/doctoring/opencode-review-quality-evaluation.md`](docs/doctoring/opencode-review-quality-evaluation.md)
  — current increment's measurement decision and APA 7th citations.
