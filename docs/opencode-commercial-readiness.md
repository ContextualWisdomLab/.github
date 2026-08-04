# Reusable OpenCode Commercial-Readiness Workflow

## Decision

`opencode-commercial-readiness.yml` is the organization-level implementation worker for an hourly commercial-readiness schedule. Product repositories own only a thin schedule and a trusted verification entrypoint. The central workflow owns target selection, OpenCode/NVIDIA NIM execution, credential separation, static safety enforcement, protected publication, and exact-head review requests.

This split keeps every product independently operable while avoiding copied agent logic across ScopeWeave, naruon, and other ContextualWisdomLab services. A product can opt in, pin one immutable central commit, and retain its own language, domain, deployment, and acceptance-test contract.

## Why the verification contract stays in the product repository

A central workflow cannot correctly infer every product's quality gates. A psychometrics package may require Rust CPU/GPU parameter-recovery experiments; an audio product may require known-signal extraction; a data service may require database concurrency and migration tests. Generic commands such as `npm test` or `pytest` are insufficient and arbitrary command inputs create a broad injection surface.

Each product therefore maintains one reviewed script below `.github/scripts`, normally `.github/scripts/commercial_readiness_verify.sh`. The central workflow checks out that script from the protected default branch into a separate `trusted-policy` directory, hashes it before model execution, forbids the agent from changing the corresponding workspace path, and executes the trusted copy against the modified workspace. The model cannot weaken the verification contract it must pass.

## Reusable caller

The product repository owns the hourly schedule and grants only the permissions required by the reusable job.

```yaml
name: Hourly commercial readiness

on:
  schedule:
    - cron: "17 * * * *"
  workflow_dispatch:

permissions: read-all

concurrency:
  group: hourly-commercial-readiness-${{ github.repository }}
  cancel-in-progress: false

jobs:
  maintain:
    permissions:
      actions: read
      checks: read
      contents: write
      issues: write
      pull-requests: write
    uses: ContextualWisdomLab/.github/.github/workflows/opencode-commercial-readiness.yml@<immutable-40-character-commit-sha>
    with:
      default_branch: develop
      verification_script: .github/scripts/commercial_readiness_verify.sh
      opencode_model: qwen/qwen3-coder-480b-a35b-instruct
      opencode_version: <reviewed-opencode-version>
      agent_timeout_minutes: 25
      product_gap_labels: buyer-gap,commercial-readiness,security,reliability,performance
    secrets:
      NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}
```

The reusable workflow reference must be a 40-character commit SHA. A product release, tag, branch, or floating `main` reference is not an acceptable production pin.

## State machine

The workflow processes one bounded target per invocation.

1. **Validate the caller contract.** The model identifier, OpenCode version, timeout, product-gap labels, and verification-script path are bounded before any repository write.
2. **Select one trusted target.** Ready pull requests precede Draft pull requests. The branch must live in the caller repository and be authored by an owner, member, collaborator, or explicitly trusted dependency-automation account. Fork code never reaches the model.
3. **Select a product gap when the queue is empty.** Existing issues are ranked only by caller-supplied bounded labels. The workflow does not invent a broad roadmap item. If no labeled issue exists, it fails without creating work.
4. **Separate trusted policy and mutable work.** The protected default branch is checked out to `trusted-policy`; the exact pull-request head or protected baseline is checked out to `workspace`. Neither checkout persists credentials.
5. **Run OpenCode with NVIDIA NIM.** `NVIDIA_NIM_API_KEY` is scoped only to the model step. OpenCode uses the NVIDIA OpenAI-compatible endpoint and never invokes GitHub Copilot.
6. **Enforce immutable boundaries.** History rewrites, whitespace errors, trusted verification-script edits, review-agent workflow changes, submodule changes, credential-like literals, private keys, and `pull_request_target` additions fail closed.
7. **Execute product-owned acceptance.** The untouched, hash-verified default-branch script runs against the workspace. The product remains responsible for complete docstrings, 100% changed-module coverage, realistic domain tests, security checks, cloud E2E, and release evidence.
8. **Publish without the model credential.** Only the publication step receives `GH_TOKEN`. An existing pull-request head must still equal the exact starting SHA. New product work opens as Draft. Ready work may only request protected squash auto-merge.
9. **Request exact-head review.** A head-specific marker makes the CodeRabbit request idempotent. Existing Noema, OpenCode-review, Strix, security, unresolved-thread, independent-approval, and branch-protection rules remain authoritative.

## Credential boundary

The workflow intentionally separates model execution, product verification, and GitHub publication.

| Phase | `NVIDIA_NIM_API_KEY` | `GH_TOKEN` | Persisted checkout credential |
|---|---:|---:|---:|
| Selection and evidence capture | No | Yes | No |
| OpenCode implementation | Yes | No | No |
| Static and product verification | No | No | No |
| Publication and review request | No | Yes | No |

The OpenCode provider configuration contains `{env:NVIDIA_NIM_API_KEY}` rather than the credential. Raw model output is redirected to an ephemeral runner file, never printed or uploaded, and destroyed if it contains the exact credential. The publication remote is temporary and restored by a shell trap.

The separation limits accidental disclosure but is not a complete sandbox boundary. The workflow therefore accepts only trusted same-repository branches, forbids environment enumeration in the assignment, and runs centrally defined static checks before any remote write.

## Caller-owned verification requirements

A conforming verification script must accept the workspace path as its first argument, change into that workspace, fail on the first unsuccessful command, and run the complete product contract. At minimum it must cover:

- deterministic dependency installation and vulnerability audit;
- formatting, linting, static analysis, and type checking;
- realistic unit and integration tests;
- database migrations, tenant boundaries, concurrency, privacy, and failure recovery where applicable;
- 100% statement, branch, function, and line coverage for new or materially changed production modules;
- 100% beginner-readable docstrings or JSDoc for changed public and security-sensitive behavior;
- cloud or browser E2E for buyer-visible behavior;
- domain-accuracy tests, such as true-parameter RMSE recovery for psychometrics or known-signal analysis for audio;
- Rust CPU/GPU/multithreaded execution requirements for psychometric computation layers;
- LLM-dependent tests through the established contextual-orchestrator boundary using `NVIDIA_NIM_API_KEY`;
- APA 7th standards or peer-reviewed references in the relevant documentation;
- multi-word `snake_case` database objects;
- `CHANGELOG.md`, packaging, version, and release checks when the software is releasable;
- `git diff --check` and absence of skipped acceptance tests.

The central workflow does not claim success when the product script omits these gates. Repository owners must review the script itself as a protected quality-policy artifact.

## Existing review-agent non-interference

The implementation agent may not edit a workflow path identifying CodeRabbit, Noema, OpenCode review, a generic review agent, Strix, or security review. It may not replace key names, copy central review workflows into a product repository, submit an independent approval, dismiss a review, mark Draft work Ready, alter branch protection, create a manual success status, or use administrator merge.

OpenCode produces a candidate implementation and local verification evidence. It is not an approving reviewer and does not replace the existing review-agent key system.

## Failure behavior

The workflow fails without publishing partial changes when any of the following occurs:

- caller inputs are unbounded or the verification path escapes `.github/scripts`;
- the model credential is absent;
- no trusted same-repository pull request or labeled product issue is available;
- the trusted verification script is absent, changed, or unsupported;
- OpenCode exceeds its bounded timeout or exits unsuccessfully;
- raw model output contains the exact model credential;
- the agent rewrites history, changes review automation, changes submodule trust, introduces a credential-like literal, or adds `pull_request_target`;
- the caller-owned verification script fails;
- the pull-request head moves while the model is working;
- an empty queue produces no verified product change.

The workflow never force-pushes, never bypasses protection, and never converts a Draft pull request to Ready.

## Modularity

The reusable workflow is an orchestration module rather than a product runtime dependency. Products can operate without it, opt into it through an immutable pin, or replace it with another implementation while preserving the same product-owned verification contract. This supports both standalone delivery and composition into the ContextualWisdomLab/naruon MSA ecosystem.

A future contextual-orchestrator adapter may provide model routing, budget policy, structured receipts, and multimodal test access. That adapter must preserve the same credential separation and must not inherit review-agent approval authority.

## References

GitHub, Inc. (n.d.). *Security hardening for GitHub Actions*. GitHub Docs. Retrieved August 4, 2026, from https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions

International Organization for Standardization. (2023). *Information technology—Artificial intelligence—Management system* (ISO/IEC Standard No. 42001:2023). https://www.iso.org/standard/81230.html

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218

National Institute of Standards and Technology. (2024). *Artificial intelligence risk management framework: Generative artificial intelligence profile* (NIST AI 600-1). https://doi.org/10.6028/NIST.AI.600-1

NVIDIA Corporation. (n.d.). *NVIDIA NIM APIs*. NVIDIA API Catalog. Retrieved August 4, 2026, from https://build.nvidia.com/explore/discover

OpenCode. (n.d.). *Providers*. Retrieved August 4, 2026, from https://opencode.ai/docs/providers/

OWASP Foundation. (2025). *OWASP Top 10 for large language model applications 2025*. https://genai.owasp.org/llm-top-10/
