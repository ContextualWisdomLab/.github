# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth.

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include (no `.`/`..`); a lone `--require-hashes` directive is not trust evidence. See [`docs/doctoring/hourly-nvidia-nim-autofix.md`](docs/doctoring/hourly-nvidia-nim-autofix.md).
Conflict-scope roots fail closed when the immediate parent directory is a symbolic link.
OriginWeave hourly NVIDIA NIM repair is a thin caller at minute 10. See [`docs/doctoring/originweave-hourly-review-caller.md`](docs/doctoring/originweave-hourly-review-caller.md).
nonnest2 hourly NVIDIA NIM repair is a thin caller at minute 16. See [`docs/doctoring/nonnest2-hourly-review-caller.md`](docs/doctoring/nonnest2-hourly-review-caller.md).

Organization edge runtimes use Cloudflare Pingora. Do not add or preserve active Nginx containers, packages, commands, service/config files, or Kubernetes Nginx ingress annotations/classes. Read [`docs/policies/PINGORA_EDGE_POLICY.md`](docs/policies/PINGORA_EDGE_POLICY.md) and ADR-0019 before changing HTTP edge, static-serving, ingress, TLS, or proxy deployment behavior.
