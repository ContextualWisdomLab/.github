# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth.
Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include (no `.`/`..`); a lone `--require-hashes` directive is not trust evidence. See [`docs/doctoring/review-inline-comment-422-fallback.md`](docs/doctoring/review-inline-comment-422-fallback.md).

Multi-line GitHub suggestions must keep start_line/start_side on the current-head hunk.
One-at-a-time 422 retries must keep multi-line start_line/start_side.


Current increment: surviving OpenCode suggested diffs become GitHub
`suggestion` blocks; retry requires a real HTTP 422 (CWE-1288). See
[`ARCHITECTURE.md`](ARCHITECTURE.md) and
[`docs/doctoring/review-inline-comment-422-fallback.md`](docs/doctoring/review-inline-comment-422-fallback.md).
Leftover overview receipts sanitize path and phrase so a leftover cannot close the HTML comment or reopen a suggestion fence.
