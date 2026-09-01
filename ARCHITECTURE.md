# Architecture — ContextualWisdomLab `.github`

This repository is the organization control plane. It is not naruon and it
does not own product data. Sibling products remain standalone modules; this
repo publishes org profile assets, reusable required workflows, and the
review/merge schedulers those products consume. The live gap snapshot is
[`docs/product-technical-gap-baseline.md`](docs/product-technical-gap-baseline.md);
it is not merge authorization. Figma File ID is N/A (no customer UI here).

## System context

```mermaid
flowchart LR
  Operator["Operator / reviewer"]
  Agents["Agents on AGENTS.md"]
  Project["GitHub Project #1"]
  Hub["This repo: org .github"]
  Products["Owned products<br/>naruon · orchestrator · engines"]
  Runner["Required workflows in each repo context"]

  Operator --> Hub
  Agents --> Project
  Agents --> Hub
  Project --> Hub
  Hub --> Runner
  Runner --> Products
  Products -->|"standalone or as module"| Operator
```

## Repository public-surface reconciliation

Repository-facing metadata is an organization control-plane responsibility,
while product README content remains owned by each sibling repository. The
reviewed desired state lives in `config/repository-metadata.json` and
`config/repository-label-taxonomy.json`. Pull requests validate both manifests
and their reconciliation behavior without write authority. Scheduled/manual
apply runs only from trusted `.github/main` after validation.

```mermaid
flowchart TD
  Desired["reviewed metadata + label desired state"]
  Validate["read-only exact-revision validation"]
  Preconditions{"leaf README badge / docs source live?"}
  Apply["trusted protected-main apply"]
  Repo["description + topics"]
  Pages["Pages state"]
  Labels["reviewed issue / PR labels"]
  Verify["live public-state re-read"]
  Hold["fail this leaf; continue siblings"]

  Desired --> Validate
  Validate --> Preconditions
  Preconditions -->|"no"| Hold
  Preconditions -->|"yes"| Apply
  Apply --> Repo
  Apply --> Pages
  Apply --> Labels
  Repo --> Verify
  Pages --> Verify
  Labels --> Verify
```

The metadata reconciler is convergent: already-correct descriptions/topics and
legacy default-branch `/docs` Pages sites receive no write; absent or drifted
Pages state is created/updated, and disabled Pages is deleted. Exact DeepWiki
badge state is a leaf-owned precondition, including a fail-closed contradiction
when desired state disables DeepWiki while the badge remains live. Label
reconciliation manages only taxonomy-declared labels and preserves unrelated
priority/status/area labels. Failures aggregate after independent repositories
or assignments are attempted, so one blocked leaf never serializes the fleet.
Scheduled/manual applies share a ref-scoped lane and do not cancel active apply
work midway. See ADR-0020 and the operational baseline for the authority and
live-verification contract.

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

## aFIPC hourly caller

`afipc-hourly-review-repair.yml` is a thin, read-only caller at minute
2. It names `ContextualWisdomLab/aFIPC` and protected `master`, maps
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

## Exact-artifact SBOM attestation

```mermaid
flowchart TD
  Seal["Six-file sealed artifact"]
  Read["verify-evidence-artifact: actions/contents read"]
  Sign["attest-exact-artifacts after verify"]
  Offline["SHA256SUMS + README + bundles"]
  Fail["Fail closed; no OIDC token"]

  Seal --> Read
  Read -->|"invalid JSON, digest, or identity"| Fail
  Read -->|"valid"| Sign
  Sign --> Offline
```

Caller inputs enter shell steps only as named environment variables. This
workflow does not claim SLSA Build L3.

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

- Required review workflows execute **base-branch** scripts. A PR that edits
  those workflows cannot widen its own `pull_request_target` token.
- Reviewer agents stay `edit: deny`. They judge; they do not implement.
- Repository public-surface writes execute only from trusted `.github/main`;
  pull-request validation remains read-only and leaf README changes keep their
  repository-local review boundary.
- Central Semgrep binds one job-level `SEMGREP_IMAGE` digest for log
  evidence, manifest inspect, and `docker run` so buyers can reconstruct
  the exact scanner that produced SARIF.
- OpenCode remains the review reasoner. Deterministic code may repair only
  trusted `path:line` source-line digest bindings on LLM probes; it never
  invents a hypothesis, observed result, or verdict.
- Sandbox helpers copy the workspace, drop secret environment values unless
  explicitly allowlisted by **name**, and run subprocesses with `shell=False`.
  Web E2E readiness URLs are loopback-only; see
  [`docs/doctoring/sandboxed-web-readiness-loopback-boundary.md`](docs/doctoring/sandboxed-web-readiness-loopback-boundary.md)
  and [`docs/adr/0004-sandboxed-web-readiness-loopback-boundary.md`](docs/adr/0004-sandboxed-web-readiness-loopback-boundary.md).
- Logs and review receipts redact credential shapes (tokens, bearer values,
  known provider prefixes). They do not mask operational PII that the
  control plane must process.
- LLM and scheduled agents bind `NVIDIA_NIM_API_KEY` (env may be
  `NVIDIA_API_KEY`). They never use `COPILOT_GITHUB_TOKEN`. Existing
  review-agent key schemes stay unchanged.
- Rust remains the psychometric arithmetic owner. Repair never substitutes
  Python for scoring math.
- Downloaded SBOM and distribution bytes are inert. The signing job does
  not import, install, or unpack them.

## Quality gates

`scripts/ci/` ships with 100% statement/branch coverage and 100% docstrings.
CI installs Python tools only with `pip install --require-hashes`. Contract
tests pin workflow structure and governance prose so drift fails closed. The
repository-public-surface workflow additionally holds both reconciliation
scripts to 100% statement/branch coverage and 100% docstrings before its
privileged apply job can run.
The trusted `uv` exporter is downloaded from the literal GitHub Releases URL for
`uv` 0.12.1; `releases.astral.sh` is not the network sink.
An exact-base `uv.lock` may additionally expose source from an organization-owned
GitHub repository pinned to a full commit: the secret-free image build verifies
the fetched revision and makes its source importable without running package
build or installation hooks. Pull-request execution remains networkless.
Root-level lock files are independent environments unless an explicit include
relationship says otherwise; only one unambiguous two-file supplement pair may
be recovered together, so unrelated toolchains cannot create a synthetic
resolver conflict.

## Related durable documents

- [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) — mission and
  ecosystem.
- [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md)
  — Project #1 operation.
- [`docs/pr-review-and-merge-procedure.md`](docs/pr-review-and-merge-procedure.md)
  — bot/agent exact-head review and merge procedure.
- [`PR_GOVERNANCE_AUDIT.md`](PR_GOVERNANCE_AUDIT.md) — live review/merge
  contract.
- [`docs/adr/0020-repository-public-surface-reconciliation.md`](docs/adr/0020-repository-public-surface-reconciliation.md)
  — desired-state ownership, trust boundary, and convergence decision.
- [`docs/doctoring/repository-public-surface-reconciliation.md`](docs/doctoring/repository-public-surface-reconciliation.md)
  — current operational baseline and live-verification contract.
- [`docs/doctoring/hourly-nvidia-nim-autofix.md`](docs/doctoring/hourly-nvidia-nim-autofix.md)
  — current increment's repair-worker decision and APA 7th citations.
- [`docs/doctoring/semgrep-image-digest-single-source.md`](docs/doctoring/semgrep-image-digest-single-source.md)
  — single-source Semgrep digest for log evidence and `docker run`.
- [`docs/doctoring/opencode-llm-review-publication.md`](docs/doctoring/opencode-llm-review-publication.md)
  — LLM probe publication without inventing observed proof.
- [`docs/doctoring/opencode-exact-vcs-dependency-evidence.md`](docs/doctoring/opencode-exact-vcs-dependency-evidence.md)
  — import-only exact source dependencies for networkless coverage.
- [`docs/doctoring/fast-mlsirm-hourly-review-caller.md`](docs/doctoring/fast-mlsirm-hourly-review-caller.md)
  — product-specific psychometric repair heartbeat and scientific gates.
- [`docs/doctoring/exact-artifact-sbom-attestation.md`](docs/doctoring/exact-artifact-sbom-attestation.md)
  — current increment's attestation decision and APA 7th citations.
- [`docs/doctoring/sandboxed-web-readiness-loopback-boundary.md`](docs/doctoring/sandboxed-web-readiness-loopback-boundary.md)
  — loopback-only web E2E readiness polling and APA 7th citations.
