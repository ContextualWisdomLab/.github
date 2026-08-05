# Hourly NVIDIA NIM PR maintenance

## Decision

The organization-owned pull-request repair loop runs once per hour and dispatches at most one file-scoped repair for a repository in each execution. The repair worker uses OpenCode with the organization secret `NVIDIA_NIM_API_KEY`; it does not use `COPILOT_GITHUB_TOKEN`, GitHub Models, or the credentials of the existing read-only review agents.

The review and repair responsibilities remain separate:

- the existing OpenCode/Noema review path continues to publish independent current-head review evidence;
- the new NVIDIA NIM worker may edit only paths named by current actionable review threads;
- all edits produce a new head that must pass the normal review, coverage, security, and branch-protection gates;
- the repair worker never approves, merges, publishes, or releases its own change.

This is an organization-central MSA component. Leaf repositories call the reusable workflow by immutable commit SHA and retain only repository-specific cadence and target metadata.

## Execution contract

1. The scheduler runs at minute 23 of every hour.
2. It inspects a bounded number of open pull requests and dispatches at most one repair.
3. A head-specific marker prevents repeated work for one hour.
4. Only same-repository heads are writable.
5. Review text and PR text are untrusted; the authoritative edit scope is the validated path list produced by the central context collector.
6. The worker re-reads live base/head metadata before checkout and again before push.
7. Missing `NVIDIA_NIM_API_KEY`, missing file-scoped review evidence, moved heads, out-of-scope edits, unresolved merge markers, or malformed metadata fail closed.
8. OpenCode has file-edit permission but no shell, task, web, LSP, or external-directory permission.
9. The NVIDIA endpoint is configured as an OpenAI-compatible provider at `https://integrate.api.nvidia.com/v1`.
10. GitHub write credentials remain separate from inference credentials. The existing OpenCode App OIDC exchange and review-token fallback are used only for GitHub API and Git transport operations.

## Immutable source boundary

GitHub documents that the ordinary `github` context in a reusable workflow describes the caller. The scheduler therefore requests a GitHub OIDC token and extracts `job_workflow_sha` for reusable calls, falling back to `workflow_sha` for direct executions. The corresponding workflow reference must identify the expected central workflow path, and the resulting 40-character SHA is used for checkout. A caller cannot redirect privileged scheduler code to a mutable branch.

The worker applies the same rule to its own `workflow_sha`. All third-party Actions and the OpenCode binary are pinned by immutable digest or SHA.

## Model-compute allocation

The current repair operation is intentionally a single bounded editing agent because the task already has a narrow review finding and an authoritative file allowlist. Multi-agent recursion would add coordination surface without evidence of benefit for this low-entropy operation.

The broader commercial-development loop should route compute by task structure rather than always using one topology:

- straightforward review repair: one editing agent plus independent reviewers;
- ambiguous cross-module defect: planner, implementation worker, and verifier;
- research-heavy architectural change: parallel evidence specialists followed by an independent synthesizer;
- high-risk release decision: independent verification paths with no shared intermediate verdict.

This direction is consistent with Conductor and TRINITY, which treat role assignment, worker selection, communication topology, and recursion depth as adaptable test-time decisions. Fugu operationalizes those ideas by routing work across a swappable model pool. The current workflow fixes agent count and recursion depth at one; future contextual-orchestrator integration must add an ablation proving that any deeper topology improves correctness or risk detection enough to justify its additional compute.

## Secret and rollback operations

Required organization secret:

```text
NVIDIA_NIM_API_KEY
```

The workflow binds it only to the process variable expected by OpenCode:

```text
NVIDIA_API_KEY
```

Rollback is deterministic:

1. disable leaf callers of `nvidia-nim-pr-maintenance.yml`;
2. remove the hourly schedule or set `dry_run: true`;
3. retain the existing review/merge scheduler and independent review workflows;
4. revert the two NVIDIA NIM workflow files and wrapper script;
5. confirm no active `nvidia-nim-pr-review-autofix` run remains.

No rollback step weakens required checks or review protection.

## Verification evidence

The merge gate requires:

- static workflow-contract tests;
- wrapper unit tests and 100% production coverage/docstrings;
- actionlint and changed-file syntax checks;
- security, CodeQL, Semgrep, secret-scan, dependency, and Scorecard checks;
- an exact-head dry run that dispatches no worker;
- an exact-head controlled fixture proving one allowed edit can be committed while an out-of-scope edit is rejected;
- independent approval by a reviewer other than the last pusher.

## References

GitHub. (2026). *OpenID Connect reference*. GitHub Docs. https://docs.github.com/en/actions/reference/security/oidc

GitHub. (2026). *Reusing workflow configurations*. GitHub Docs. https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations

Nielsen, S., Cetin, E., Schwendeman, P., Sun, Q., Xu, J., & Tang, Y. (2025). *Learning to orchestrate agents in natural language with the Conductor* [Preprint]. arXiv. https://arxiv.org/abs/2512.04388

NVIDIA. (2026). *API reference for NVIDIA NIM for large language models*. NVIDIA Documentation. https://docs.nvidia.com/nim/large-language-models/latest/api-reference.html

OpenCode. (2026). *Providers*. https://opencode.ai/docs/providers

Sakana AI. (2026). *Sakana Fugu: Multi-agent system as a model*. https://sakana.ai/fugu/
