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

## Skills, root-cause fixes, and handoff

- Read the installed `SKILL.md` before using a skill; choose it for the task,
  not merely because it is installed. Apply Ponytail after tracing the affected
  callers: reuse the canonical owner, existing code, standard library, native
  platform, and installed dependencies before adding an implementation.
- Use Superpowers `systematic-debugging` for failures, `test-driven-development`
  for behavior changes, and `verification-before-completion` for delivery
  claims. Reproduce the failure, fix its shared cause, and run the regression
  check. Never claim RED was observed unless the pre-fix check actually failed.
  Use `autoresearch` only for a bounded experiment with a baseline, measurable
  metric, and result log; documentation-only edits need no experiment scaffold.
- Use CodeGraph in the exact worktree being changed; initialize a missing index
  and sync an unhealthy index. An explicitly read-only scope takes precedence:
  do not initialize or sync there; report a missing or stale index and use
  focused source inspection instead. Use Context7 for external library/API contracts
  and DeepWiki for repository context, then verify against current source and
  official documentation. Report unavailable tools or stale indexes explicitly.
  Apply `humanize-korean`/`im-not-ai` to Korean prose without changing facts;
  use `adr-author` when recording an architectural decision.
- Confirm repository, worktree, branch, dirty files, and live PR head/base before
  editing. Preserve other agents' changes; coordinate one writer per shared
  delta and use isolated worktrees for independent changes. Fix owner defects
  there and consume released contracts, not copied source or temporary branches.
- Keep progress in the existing Project/PR, not a competing private tracker.
  Handoffs include owner, worktree, PR URL, head/base SHA, commands and results,
  unresolved findings, and the next safe action. Count only verified acceptance
  items in progress percentages and state the denominator. Local tests, protected
  merge, and live operation are separate milestones; queued checks, enabled
  auto-merge, and a lost test-session handle prove none of them.

## Actions queue and protected-merge procedure

These are required operating rules, not evidence that every current workflow
implements them. Check the exact workflow revision and its regression/live-run
evidence; record any gap in the owning PR instead of claiming a docs-only fix
changed runtime behavior.

- Use `github-actions-privileged-pr-scan` when a PR scanner can reach secrets,
  and use `github-robot-review-gate` plus `babysit-pr` when diagnosing or
  monitoring a protected PR. If a named skill is unavailable, preserve its
  fail-closed trust boundary and exact-current-head evidence rules manually.
- PR-triggered workflow concurrency must be trigger-aware. Group by workflow,
  target repository, and pull request number with `cancel-in-progress: true`;
  do not include the head SHA, because that prevents a new head from cancelling
  its predecessor. Non-PR triggers need an explicit collision-safe fallback.
- Do not let a rerun of an older run ID re-enter the live PR group and cancel
  newer evidence. Use the PR number only when `github.run_attempt == 1`;
  isolate reruns with a `rerun-` prefix and `github.run_id`. Retain exact-live-head
  admission before privileged work and evidence publication. An admission job
  cannot undo a cancellation already caused by workflow-level concurrency.
- Put concurrency at workflow scope to coalesce whole runs, including their
  bootstrap jobs. Job-level concurrency controls only the jobs carrying that
  setting; do not infer a runner-admission ordering guarantee. See GitHub's
  [workflow and job concurrency contract](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
  Keep release, publish, deploy, and migration work outside cancellable PR
  evidence groups; preserve their serialization and idempotency safeguards.
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
  scheduled scan to compensate for incorrect concurrency. For superseded-head
  cleanup, cancel only runs
  proven to belong to a superseded head of the same PR, then poll
  `actions/runs/{run_id}` with a bounded retry. Treat cancellation as complete
  only when `status == "completed"` and `conclusion == "cancelled"`; an HTTP
  202 from cancel or force-cancel is not completion.
- Classify a run's PR head by event-specific evidence before cancellation.
  Do not confuse runtime `github.sha`/`GITHUB_SHA` with REST run `head_sha`.
  Native and organization-required `pull_request_target` runs observed here
  retain the original PR head in REST `head_sha`, while their
  `pull_requests[].head.sha` association can refresh after another push.
  A current PR association alone cannot prove an old run checks the current
  revision. Bind the recorded run revision to the repository/PR identity and
  revalidate the live PR before cancellation; preserve runs whose identity
  cannot be proven. In the 2026-09-05 REST observation,
  [CO run 33949656057](https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/33949656057)
  retained revision `1481c595dc1d16e7bf4b65addaf0bd30322cf2b8` while its
  association named `6d1b30803888e893d7bdbdf4d12605a16c36162d`.
  Main `6d7fbebec8aec31d88a30a36e71ca5b3925d241d` still permits association-only
  coalescer authority; [#1899](https://github.com/ContextualWisdomLab/.github/pull/1899)
  tracks the proposed runtime correction. This procedure does not prove that
  correction is deployed. A `repository_dispatch` run executes on the control-plane
  branch, so bind it to the validated target
  repository, PR number, and target-head SHA from its payload or run name.
  Do not use a dispatch run's top-level `head_sha` as its target PR head.
  Same-head duplicate coalescing and inactive-PR cleanup need their own
  eligibility checks; neither is evidence of a superseded head. If current-head
  evidence is accidentally cancelled, use the replacement eligibility and
  deduplication rules above; never cancel healthy current-head evidence merely
  to force a replacement.
- Before every review, retry, push, or merge claim, re-fetch the PR's exact head
  SHA, base SHA, review threads, required checks, and ruleset result. A push
  invalidates earlier checks and reviews. Never self-approve, dismiss reviews,
  force-push, disable a security gate, or use admin bypass for product or
  security changes.
- Queue pressure alone grants no bypass authority. An explicitly user-authorized
  Actions bootstrap exception must identify the exact diff and the causal gate
  it repairs, preserve independent exact-head review and unaffected gates, and
  record post-merge verification. Never extend that exception to unrelated PRs
  or treat the bypass itself as passing protected-gate evidence.

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

## Verifying a "superseded — closing" claim

`docs/org-required-workflow-rollout.md` allows retiring a PR "only after verified
complete successor carryover of every unique valid delta; redundancy alone is not
a close instruction." Verify that carryover against the tree, not against how
convincing the closing comment reads. These commands narrow it down; none of
them alone proves succession.

- Read what the branch actually contributes with a **three-dot** diff:
  `git diff --stat origin/main...<head>`. Two-dot (`origin/main <head>`) also
  reports changes `main` gained that the branch lacks, which on a stale PR reads
  as large phantom deletions by the PR. A long-lived branch's title records what
  it was opened for, so it is not evidence of current scope either.
- Look for each claimed-inherited piece by content: `git grep -lF "<string>"
  origin/main --` (use `-F`; `git grep` treats the pattern as a regex otherwise).
  No output means that exact string is absent from `main` — strong evidence the
  delta is missing, but not proof, since a successor may have renamed or
  restructured the same behaviour. Conversely a match is not proof of inheritance:
  the same name can carry different behaviour.
- `git show origin/main:<path>` tells you whether the path exists on `main`
  **now**. A non-zero exit does not mean the content never landed — it may have
  landed and later been deleted — and success does not mean the successor kept
  the predecessor's changes to it.
- Ancestry is the wrong tool here. `git merge-base --is-ancestor <commit> main`
  answers "was this commit object merged", not "is this content on `main`". This
  repository mixes squash merges with real merge commits, so a squash-carried
  delta reports false while a later-reverted one still reports true.
- When the delta is provably absent and no successor accounts for it, reopen
  (`gh api repos/<owner>/<repo>/pulls/<n> -X PATCH -f state=open`) and comment the
  commands and their output. Missing evidence is not the same as disproven
  succession: if the check is merely inconclusive, say so and ask, rather than
  reopening or letting the closure stand unexamined.

## Supersession and constant-change review

- When a large PR is narrowed into successors, verify the **union** of those
  successors against the original's full diff — not merely that each successor's
  own tests pass. `#1871` was closed in favor of `#1877` plus `#1879`; both
  successors were green, but neither carried `#1871`'s coverage/docstring delta,
  so the required 100% gate stayed broken on `main` until `#1883` recovered it.
  "Each piece works" and "the pieces together still cover the original's scope"
  are different questions, and only the second one needs a diff against the
  original.
- Use the per-delta commands in "Verifying a 'superseded — closing' claim" above
  against **each** successor, then ask the question those commands cannot: does
  anything in the original's scope survive in none of them? A split fails
  differently from a single bad closure — no individual successor looks wrong.
- A closure or narrowing is not self-verifying, and neither is a note recording
  it. Git-level checks show whether the text moved; they do not show whether the
  behaviour is restored. Finish by re-running the gate the original PR existed to
  fix and confirming it passes on `main` itself from a fresh clone.
- Never endorse a timeout, retry budget, or other numeric constant on a
  model-invocation path without first reading
  [`docs/product-goal-directive.md`](docs/product-goal-directive.md) section 8,
  which states that central OpenCode, Strix, and Noema accept taking more than two
  hours per model ("중앙 OpenCode, Strix, Noema는 모델당 두 시간 이상 걸릴 수 있음을
  수용한다") and that speed is not a core consideration, accuracy is
  ("속도는 핵심 고려사항이 아니며 정확성을 우선한다"). `#1889`, `#1890`, and `#1892`
  each capped a model step at 900 seconds on real evidence of a multi-hour hang,
  and all three were reverted (`#1891`, `#1895`). Compelling hang evidence does not
  exempt a change from that contract: runner occupancy is repaired at the
  admission/continuation boundary or by an explicit provider terminal signal, never
  by converting elapsed inference time into a model-failure verdict.
- Verify a citation before you rely on it, including your own. The first draft of
  the bullet above cited a section number that does not exist in that file and
  attributed a "timeout defaults to null" sentence to it that appears only in
  `#1891`'s PR body — both caught by grepping the file instead of trusting the
  summary that introduced them.
