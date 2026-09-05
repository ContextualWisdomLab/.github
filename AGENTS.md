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
- Do not let a rerun of an older run ID re-enter the live PR group and cancel
  newer evidence. Use the PR number only for the first attempt and fall back to
  `github.run_id` for reruns, or reject the rerun through exact-live-head
  admission before it can displace current work.
- Put concurrency at workflow scope when queued jobs must be coalesced before a
  runner is admitted. Job-level concurrency cannot relieve a saturated runner
  queue because it is evaluated only after job admission.
- Subscribe only to pull-request actions that can produce useful work. The
  default review set is `opened`, `synchronize`, `reopened`, and
  `ready_for_review`; do not add `converted_to_draft` or `closed` merely to run
  a job-level false condition, because the workflow run still enters the
  organization queue. Add a lifecycle action only when that workflow performs
  an explicit, tested cleanup or state transition for it. A draft or close
  event whose purpose is to retire active evidence for that PR must share the
  PR evidence concurrency group and publish the required exempt/terminal state.
  An auxiliary cleanup that scans and cancels runs by API must instead use a
  lifecycle-specific group so it cannot preempt current-head evidence; compare
  the live PR state and head immediately before every cancellation. After a
  cancellation reaches its terminal state, re-read both the PR and target run;
  only if the PR is still open and non-draft and the cancelled target still
  matches its live head, enqueue at most one replacement keyed by PR, workflow,
  and target head. Revalidate that exact head again during replacement admission
  instead of treating cleanup as successful.
- Keep cleanup repository-local and event-driven. Do not restore an
  organization-wide queue sweep, unbounded sleep-based polling, or another
  scheduled scan to compensate for incorrect concurrency. Cancel only runs
  proven to belong to a superseded head of the same PR, then poll
  `actions/runs/{run_id}` with a bounded retry. Treat cancellation as complete
  only when `status == "completed"` and `conclusion == "cancelled"`; an HTTP
  202 from cancel or force-cancel is not completion.
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
