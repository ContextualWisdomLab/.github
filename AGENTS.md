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

## Verification discipline

Many agent sessions work this organization concurrently under the same standing
brief. Silence is not evidence: "I have not touched X" describes one session's
history, never the organization's actual state.

- **Before calling an item "not started" or a dependency "not adopted", check
  beyond your own session.** Search organization-wide (`gh search prs --owner
  ContextualWisdomLab "<keyword>"` — note it returns 30 results by default, so
  it is a lead, not an exhaustive sweep), check whether a dedicated repository
  already owns the responsibility, then clone the target repository and read the
  real integration surface: compose files, the module that would consume the
  dependency, its docstrings and comments. A PR-title survey cannot see
  infrastructure already deployed with no PR trail, nor a deliberate
  non-adoption decision recorded only in a code comment. Both failures are
  documented in
  [`docs/doctoring/egressweave-wardnet-adoption-audit-contextual-orchestrator-20260903.md`](docs/doctoring/egressweave-wardnet-adoption-audit-contextual-orchestrator-20260903.md).
- **A negative capability claim — "library X *cannot* do Y" — needs X's own
  source, not its README.** Clone the library and read its policy/configuration
  code and its test suite, which often carries the clearest worked example of
  the edge case in question. A feature-list summary is not sufficient evidence
  for a negative claim, least of all when that claim becomes a "do not adopt"
  recommendation other agents will treat as settled. The record above is an
  instance: a documented, tested configuration override was missed by reading
  only the README.
- **A peer restating a claim is not corroboration of it.** If two sessions both
  rely on the same summary, that is one check, not two. Independent
  verification means each examines the primary evidence — the code, the API
  response, the log — from a different vantage point.
- **Prefer a different model family for adversarial review of your own
  conclusions.** Sessions here share a model and tend to share blind spots. A
  read-only `codex exec -s read-only -C <dir> "<prompt>"` pass has already
  caught a factual error in this very section that same-family review missed.

## Test-gate regressions and stale-PR merges

- A red required check on your PR is not proof that your diff caused it. No workflow runs
  the full `tests/` suite unconditionally on a push to `main`: the only unrestricted
  full-suite run lives in `opencode-review-dispatch.yml`, which triggers on
  `repository_dispatch` from a pull request, and the two quality workflows that do watch
  `main` are each path-filtered to their own slice. A suite-breaking merge therefore lands
  invisibly and then fails every later pull request regardless of that request's own diff.
- Reproduce a suspect failure on a clean baseline before repairing it. Run
  `git worktree add /tmp/baseline <the PR's base ref> --detach`, then `cd /tmp/baseline`
  and run `python3 -m pytest tests -q`; that takes roughly four minutes and needs no
  virtualenv. You must `cd` into the worktree: over thirty test files read repository files
  through working-directory-relative paths such as `Path(".github/workflows/...")`, so
  pointing pytest at the baseline directory from your own checkout silently tests your tree
  and reports a green baseline that proves nothing. Baseline the pull request's actual base
  or merge-base rather than `origin/main` once `main` has moved past it. If the failure
  reproduces on the baseline it is pre-existing: repair it as its own pull request and name
  the change that introduced it.
- When you change a workflow file or a `scripts/ci/` module, grep the whole `tests/` tree
  for every literal you touched — event-type strings, cron expressions, environment-variable
  names, tuple members, pinned digests — not only the obviously named sibling test. A change
  can satisfy one oracle and still leave a second, independent one stale.
- `tests/test_pr_review_autofix_nvidia_nim_contract.py` pins the exact `git hash-object`
  digest of `.github/workflows/opencode-review-dispatch.yml`. Any byte change to that
  workflow makes the pin stale and fails a required gate for every open pull request —
  reverts included, because a revert restores the original bytes while the pin stays on the
  reverted value. Recompute it with
  `git hash-object .github/workflows/opencode-review-dispatch.yml`;
  `tests/test_opencode_rust_coverage_toolchain_contract.py` re-derives the same constant by
  regular expression, so correcting the single declaration fixes both.
- Production code under `scripts/ci/` branches on `GITHUB_ACTIONS`, and pytest inherits that
  variable in CI, so a failure class exists that cannot reproduce locally. Before calling a
  scheduler change clean, run the affected tests both ways, including
  `GITHUB_ACTIONS=true python3 -m pytest <paths>`.
