# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth.

Trusted-uv download retries 5xx/429 only; other 4xx fail closed on the first attempt. Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include (no `.`/`..`); a lone `--require-hashes` directive is not trust evidence. See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`docs/doctoring/trusted-uv-transient-download-retry.md`](docs/doctoring/trusted-uv-transient-download-retry.md).
