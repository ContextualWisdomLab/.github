# Agent source-fix command lane

- Added a bounded organization-wide `@cwl-source-fix` command for trusted maintainers, with compatibility recognition for `@opencode-agent fix` and `@opencode-agent repair`.
- Bound every mutation request to the exact repository, PR, source comment, actor, base SHA, and head SHA, and added a durable Actions-artifact invocation ledger.
- Restricted edits to the complete authenticated GitHub PR Files set, excluding removed files, `.github/`, `scripts/ci/`, forks, new paths, and the central `.github` repository itself.
- Routed model work only through contextual-orchestrator `orchestrator/free`, denied shell/web/external tool escape, restored temporary model configuration before scope verification, and required an unchanged live head before a normal non-force push.
