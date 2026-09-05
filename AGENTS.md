# AGENTS.md — ContextualWisdomLab .github

<!-- CWL-ENTRY -->
> **Agents: read the master context FIRST.** Before any work, read [`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission · naruon-as-platform + inter-component UML · cross-cutting disciplines · conventions · roadmap · current state), the live **GitHub Project #1** <https://github.com/orgs/ContextualWisdomLab/projects/1> (work/roadmap source of truth), the full spec **ContextualWisdomLab/naruon#974**, the live gap snapshot [`docs/product-technical-gap-baseline.md`](docs/product-technical-gap-baseline.md) (not merge authorization; Figma File ID for this repo is N/A per [`docs/adr/0002-product-technical-gap-baseline.md`](docs/adr/0002-product-technical-gap-baseline.md)), and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The repo/Project — not any private agent memory — is the source of truth. The standing autonomous operating directive for the continuous PR review→fix→merge→develop loop across the ecosystem is [`docs/product-goal-directive.md`](docs/product-goal-directive.md) — a `/goal` session's 4000-character pointer refers to it; read the full directive before running or configuring any such loop.

Materialize accepts only exact SHA-256 pins, a bounded relative `-r` include
(no `.`/`..`), or an organization-owned HTTPS Git source pinned to a full
commit and exposed without running build hooks; a lone `--require-hashes`
directive is not trust evidence. See
[`docs/doctoring/opencode-exact-vcs-dependency-evidence.md`](docs/doctoring/opencode-exact-vcs-dependency-evidence.md).
Conflict-scope roots fail closed when the immediate parent directory is a symbolic link.
All 18 product hourly review-repair callers (OriginWeave at minute 10, nonnest2 at minute 16, and 16 others) are one file, [`.github/workflows/hourly-review-repair.yml`](.github/workflows/hourly-review-repair.yml), a `github.event.schedule` lookup table rather than 18 near-copy-pasted files. See [`docs/doctoring/hourly-review-repair-single-file-consolidation.md`](docs/doctoring/hourly-review-repair-single-file-consolidation.md); the per-repository doctoring records (e.g. [`docs/doctoring/originweave-hourly-review-caller.md`](docs/doctoring/originweave-hourly-review-caller.md), [`docs/doctoring/nonnest2-hourly-review-caller.md`](docs/doctoring/nonnest2-hourly-review-caller.md)) remain as historical background per repository.
Organization edge runtimes use Cloudflare Pingora. Do not add or preserve active Nginx containers, packages, commands, service/config files, or Kubernetes Nginx ingress annotations/classes. Read [`docs/policies/PINGORA_EDGE_POLICY.md`](docs/policies/PINGORA_EDGE_POLICY.md) and ADR-0019 before changing HTTP edge, static-serving, ingress, TLS, or proxy deployment behavior.

Semgrep hosted scans bind one job-level `SEMGREP_IMAGE` digest for log evidence, manifest inspection, and `docker run`. See [`docs/doctoring/semgrep-image-digest-single-source.md`](docs/doctoring/semgrep-image-digest-single-source.md).
OpenCode may repair only trusted `path:line` bindings on LLM probes that already carry an independent proof and source-line digest. See [`docs/doctoring/opencode-llm-review-publication.md`](docs/doctoring/opencode-llm-review-publication.md).

Central review routes through the vendored **contextual-orchestrator** gateway
sidecar (`scripts/ci/contextual_orchestrator_review_sidecar.sh`). The five
provider secrets (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
`NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) enter its KV
as bootstrap transport in the same process that discovers models and serves;
OpenCode, Noema, and Strix all use the fail-closed zero-cost pool
`orchestrator/free`. Strix was switched onto `orchestrator/free` on
2026-08-30, superseding the prior `orchestrator/auto` (provider-diverse,
non-free-admitting) default; private targets still require ZDR-compliant
routes under [`scripts/ci/zdr_policy.py`](scripts/ci/zdr_policy.py). That
switch was made by an autonomous agent session, not per any owner decision —
see [`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`](docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md)'s
2026-08-30 amendment and its 2026-08-31 correction, which retracts an earlier
false claim of explicit owner direction and records the resulting
availability risk as open and unreviewed, not accepted.
The materialization contract is also covered by [`docs/doctoring/exact-artifact-sbom-attestation.md`](docs/doctoring/exact-artifact-sbom-attestation.md).

## Actions queue and protected-merge procedure

- Use `github-actions-privileged-pr-scan` when a PR scanner can reach secrets,
  and use `github-robot-review-gate` plus `babysit-pr` when diagnosing or
  monitoring a protected PR. If a named skill is unavailable, preserve its
  fail-closed trust boundary and exact-current-head evidence rules manually.
- PR-triggered workflow concurrency must be trigger-aware. Group by workflow,
  target repository, and pull request number with `cancel-in-progress: true`;
  do not include the head SHA, because that prevents a new head from cancelling
  its predecessor. Non-PR triggers need an explicit collision-safe fallback.
- Put concurrency at workflow scope when queued jobs must be coalesced before a
  runner is admitted. Job-level concurrency cannot relieve a saturated runner
  queue because it is evaluated only after job admission.
- Keep cleanup repository-local and event-driven. Do not restore an
  organization-wide queue sweep, polling `sleep`, or another scheduled scan to
  compensate for incorrect concurrency. Cancel only runs proven to belong to a
  superseded head of the same PR, then verify each accepted cancellation
  reaches `completed/cancelled`.
- Classify a run's PR head by event-specific evidence before cancellation.
  `pull_request` may use the run's top-level `head_sha`, but
  `pull_request_target` records the trusted base there; use its PR association
  and immutable run name/event payload instead. A `repository_dispatch` run
  also executes on the control-plane branch, so bind it to the validated target
  repository, PR number, and target-head SHA from its payload or run name.
  Never compare either event's top-level `head_sha` directly with the live PR
  head. If a current-head dispatch is cancelled while deduplicating, enqueue
  exactly one replacement for that PR and workflow and verify the replacement
  carries the same live target head.
- Before every review, retry, push, or merge claim, re-fetch the PR's exact head
  SHA, base SHA, review threads, required checks, and ruleset result. A push
  invalidates earlier checks and reviews. Never self-approve, dismiss reviews,
  force-push, disable a security gate, or use admin bypass for product or
  security changes.

## Cross-session agent coordination and accumulated know-how

This organization runs a fleet of independently-scheduled agent sessions sharing one
GitHub account. Sessions do not share memory, and there is no live messaging channel
between them — a `ListAgents`-style lookup from inside one such session finds no other
reachable session. The repo itself (its PRs, issues, and comment history) is the only
coordination layer that persists across sessions.

- **Check for an existing claim before starting non-trivial new work.** Before opening a
  new fix PR or resuming a stalled Gap item, look for an open PR/issue already addressing
  it, a Draft PR carrying explicit "keep Draft until ..." governance language, or an
  active comment thread, and do not duplicate it. When resuming work on a PR after a gap,
  say so once in a PR comment so the next session or the human owner sees who currently
  owns it. When you learn something reusable, add it here (or to the relevant repo's
  `AGENTS.md`/`CLAUDE.md`), not only to a PR comment or a gap-baseline doc entry — those
  are per-incident, and this file is what every future session reads first, per its own
  opening instruction to read it before any work.
- **PR-driving postures.** A PR you opened or were asked to drive is yours to keep green:
  on every CI-red event, either push a fix or post exactly one comment naming the failing
  check and why it is not yours to fix — never leave a PR you are driving both red and
  untouched. A PR you are only watching (someone else, human or agent, is actively driving
  it) gets diagnosis and a proposal, never an uninvited push.
- **Prove base-branch debt before citing it.** Before claiming a CI-red failure on your
  own PR "isn't caused by your diff," reproduce the exact failing CI command in a
  throwaway git worktree checked out at the unmodified base branch; only a failure that
  reproduces identically there is legitimate base-branch debt to cite in a standing-down
  comment. Done for real on `contextual-orchestrator#1070`: a `coverage report
  --fail-under=100` failure on `nim_benchmark.py` (missing statement/branch coverage at
  `434, 645, 671->682`) reproduced identically in a throwaway worktree on unmodified
  `origin/main`, so it was cited as pre-existing debt and tracked separately as
  `contextual-orchestrator#1075` instead of being folded into that PR's scope.
- **Org-wide GitHub Actions capacity exhaustion is a real, independently observed,
  non-code-fixable condition** — hundreds of runs queued for hours across repositories,
  jobs materializing with no runner assigned and zero steps, reproducing even on pinned
  `ubuntu-24.04` runners — already tracked in `docs/product-technical-gap-baseline.md`. A
  queued or pending required check is not a blocker to route around by re-running,
  retargeting runner images, or shortening timeouts; those address different failure
  classes. Runner-image pinning off floating `ubuntu-latest` onto explicit `ubuntu-24.04`
  (precedent: this repo's `#1870`, and `contextual-orchestrator#1072`) is a narrow,
  legitimate fix for a specific, different, independently-confirmed pattern — floating-image
  starvation with a sampled window of zero clean successes — and must not be applied as a
  generic response to ordinary queue depth.
- **Re-verify an "already implemented, no code change needed"-style claim yourself,
  against exact `file:line` evidence, before repeating it — including a human reviewer's
  own claims.** A claim can cite individually true facts and still be scoped too broadly.
  This repo's `#1884` originally claimed Noema/OpenCode/Strix review was "already fully
  routed through contextual-orchestrator's `orchestrator/free`, no code change needed."
  Independently re-checked in this checkout: the model-selection/logical-routing layer
  (`opencode.jsonc`'s `enabled_providers`/`model`/`small_model`, and
  `opencode-review-dispatch.yml`'s `OPENCODE_MODEL_CANDIDATES`) is in fact pinned to
  `contextual-orchestrator/orchestrator/free` with no NIM-branch candidate — that part of
  the claim held up. But it was bundled with the actual runtime sidecar/egress layer,
  `scripts/ci/contextual_orchestrator_review_sidecar.sh`, which — independently re-verified
  in this checkout — still requires and injects at least one of five raw provider secrets
  (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`, `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`,
  `OPENAI_API_KEY`), `git clone`s and installs `contextual-orchestrator` fresh on the
  calling runner on every invocation, and runs model discovery in-process there — not yet
  the immutable, secrets-free gateway artifact the org wants. That gap is tracked by this
  repo's `#1759` and `contextual-orchestrator#1041` comment `5550412102`. `#1884`'s own
  claim was corrected in place, in the same PR, once this was raised and independently
  re-verified point-by-point against exact `file:line` evidence — do not repeat the
  original, too-broad "already implemented" framing for this sidecar.
