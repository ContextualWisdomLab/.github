# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth.

Materialize accepts only exact SHA-256 pins, a bounded relative `-r` include
(no `.`/`..`), or an organization-owned HTTPS Git source pinned to a full
commit and exposed without running build hooks; a lone `--require-hashes`
directive is not trust evidence. See
[`docs/doctoring/opencode-exact-vcs-dependency-evidence.md`](docs/doctoring/opencode-exact-vcs-dependency-evidence.md).
Conflict-scope roots fail closed when the immediate parent directory is a symbolic link.
Strix classifies a trusted same-line LiteLLM or agents-SDK `ModelBehaviorError` as backend-unavailable only when the log has no `Vulnerabilities [1-9]`. See [`docs/doctoring/strix-model-behavior-error-fallback.md`](docs/doctoring/strix-model-behavior-error-fallback.md).
OriginWeave hourly NVIDIA NIM repair is a thin caller at minute 10. See [`docs/doctoring/originweave-hourly-review-caller.md`](docs/doctoring/originweave-hourly-review-caller.md).
nonnest2 hourly NVIDIA NIM repair is a thin caller at minute 16. See [`docs/doctoring/nonnest2-hourly-review-caller.md`](docs/doctoring/nonnest2-hourly-review-caller.md).

OpenCode may repair only trusted `path:line` bindings on LLM probes that already carry an independent proof and source-line digest. See [`docs/doctoring/opencode-llm-review-publication.md`](docs/doctoring/opencode-llm-review-publication.md).

The materialization contract is also covered by [`docs/doctoring/exact-artifact-sbom-attestation.md`](docs/doctoring/exact-artifact-sbom-attestation.md).
