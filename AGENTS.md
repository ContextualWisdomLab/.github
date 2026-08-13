# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth.

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include (no `.`/`..`); a lone `--require-hashes` directive is not trust evidence. See [`docs/doctoring/review-agent-mention-surfaces.md`](docs/doctoring/review-agent-mention-surfaces.md).

Pending and dismissed reviews do not dispatch mention agents. Submitted review bodies react through GraphQL `addReaction`, reusing the webhook `node_id` when present. A GraphQL already-reacted payload is success; a response without `data.addReaction` is a warning. The local mention job grants `issues: write` and `pull-requests: write` for optional eyes reactions; `reactions: write` is not a `GITHUB_TOKEN` permission. See [`ARCHITECTURE.md`](ARCHITECTURE.md) and [`docs/doctoring/review-agent-mention-surfaces.md`](docs/doctoring/review-agent-mention-surfaces.md).
