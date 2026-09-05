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
- **Your working tree is not evidence until you prove it is current.** A
  long-running session's checkout drifts while `main` advances roughly every
  20 minutes; on 2026-09-05 one session's `.github` tree was 218 commits
  behind, and from it re-derived an already-fixed bug and cited line numbers
  that do not exist on `main`. At every wake, and before reading any file you
  will reason about, run
  `git fetch origin main && git rev-list --count HEAD..origin/main`. If that is
  non-zero, read files as `git show origin/main:<path>` or in a fresh
  `git worktree add <dir> origin/main`, and never quote a line number you did
  not read from `origin/main`.

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

## Test-gate regressions and stale-PR merges

- A red `tests`, coverage, or `interrogate` gate on your pull request is not proof that your
  diff caused it. Full-suite execution on a push to `main` is not guaranteed: the workflows
  that run `pytest tests` on push are `paths:`-filtered, so a pairing broken outside their
  declared paths reaches `main` with no full-suite run. The breakage then surfaces on the
  next pull request whose review dispatch does run the suite, and fails it regardless of
  that request's own diff. This procedure covers the suite gates only; a red Semgrep,
  CodeQL, Strix, or Scorecard check is a different diagnosis.
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
- Read a stale pull request's own changes with a three-dot diff —
  `git diff <base>...<head>` — or with `gh pr diff`, which is already three-dot. A two-dot
  `git diff <base> <head>` renders everything the base gained since the fork point as though
  this branch deleted it, so an untouched branch reads as a mass revert.
- Content-hash pins exist under `tests/`; find them before editing a workflow. Run
  `grep -rn 'hash-object' tests/` — today that is the `git hash-object` pin of
  `.github/workflows/opencode-review-dispatch.yml`. Any byte change to a pinned file makes
  its constant stale and fails a required gate for every open pull request, reverts included,
  because a revert restores the original bytes while the pin stays on the reverted value.
  Recompute only with `git hash-object <path>`, and only for a constant you have confirmed is
  a blob pin. Nearly every other forty-hex literal under `tests/` is something else — a
  pinned action SHA, a vendored-revision pin, a synthetic fixture head, or an assertion that
  a SHA appears in a document — and pointing `hash-object` at any of those produces a wrong
  value that breaks what it replaces. A second contract re-derives the dispatch pin by
  regular expression from the first, so keep the assignment on one line and correct it in one
  place.
- Production code under `scripts/ci/` branches on `GITHUB_ACTIONS`, and pytest inherits that
  variable in CI, so a failure class exists that cannot reproduce locally. Before calling a
  scheduler change clean, run the affected tests both ways, including
  `GITHUB_ACTIONS=true python3 -m pytest <paths>`.

## Where accumulated know-how lives

Durable agent learnings are recorded in this repository, not in any session's
private memory. Read the relevant store before working on the surface it
covers — these records exist so the same class of bug is not reintroduced, and
they only pay off when an agent other than their author reads them.

- [`docs/doctoring/ci-failure-signature-triage.md`](docs/doctoring/ci-failure-signature-triage.md)
  — string-matchable catalog of the recurring red-check signatures across the
  three repositories (`opencode-review` wait-for-verdict, `strix` stale
  `workflow_sha`, `noema-review` gateway 502, expired NIM cost evidence,
  unscoped `pytest` collection, stale `head_sha` notifications,
  queued-versus-failed, same-anchor merge conflicts, futile CodeQL compat
  re-runs, cancelled-versus-failed and auto-update check starvation, and
  drafts that no gate will ever approve, review, or rebase, and the Pingora
  policy's 1 MiB Contents-API ceiling on oversized text), each
  with its verified mechanism, the action to take, and the
  actions not to take, plus the rule for deciding when a re-run can help at
  all. Also carries the
  research-grounding freshness KPIs, their measured baseline, and how to count
  them without a masked API error manufacturing a phenomenon.
- [`.jules/bolt.md`](.jules/bolt.md) — dated performance learnings for
  `scripts/ci/` as `**Learning:**` / `**Action:**` pairs. Scan it before
  optimizing anything on that surface.
- [`.jules/sentinel.md`](.jules/sentinel.md) — dated security learnings for the
  same surface as `**Vulnerability:**` / `**Learning:**` / `**Prevention:**`
  triples, covering HTML-comment breakout in serialized JSON, cross-language
  redaction parity, `shell=True` "security theater", and SSRF via redirects.
  Scan it before hardening anything on that surface.
- `docs/doctoring/` — per-incident and per-decision records generally.
