# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth.

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include (no `.`/`..`); a lone `--require-hashes` directive is not trust evidence. See [`docs/doctoring/review-inline-comment-422-fallback.md`](docs/doctoring/review-inline-comment-422-fallback.md).

OpenCode APPROVE names a current-head file only as a whole path token (`example.py.bak` does not dispose `example.py`). REQUEST_CHANGES also names a file via an identical `diff --git a/X b/X` header or matching `--- a/X` / `+++ b/X` headers. See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`docs/doctoring/review-contract-per-file-disposition.md`](docs/doctoring/review-contract-per-file-disposition.md).
