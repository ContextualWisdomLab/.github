# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth.

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include (no `.`/`..`); a lone `--require-hashes` directive is not trust evidence. See [`docs/doctoring/hourly-nvidia-nim-autofix.md`](docs/doctoring/hourly-nvidia-nim-autofix.md).
Conflict-scope roots fail closed when the immediate parent directory is a symbolic link.
OriginWeave hourly NVIDIA NIM repair is a thin caller at minute 10. See [`docs/doctoring/originweave-hourly-review-caller.md`](docs/doctoring/originweave-hourly-review-caller.md).
nonnest2 hourly NVIDIA NIM repair is a thin caller at minute 16. See [`docs/doctoring/nonnest2-hourly-review-caller.md`](docs/doctoring/nonnest2-hourly-review-caller.md).
Cursor Cloud Agents cannot complete Figma MCP OAuth against `https://mcp.figma.com/mcp` (allowlisted-client catalog; Cloud unsupported). Desktop/CLI remain the MCP path. Cloud Agents that must read Figma files store `FIGMA_ACCESS_TOKEN`, run `python3 scripts/ci/figma_rest_auth.py`, then `python3 scripts/ci/figma_rest_file.py <file-key-or-url>`. See [`docs/doctoring/figma-cloud-agent-mcp-auth.md`](docs/doctoring/figma-cloud-agent-mcp-auth.md).
