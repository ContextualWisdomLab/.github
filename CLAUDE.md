# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read first

`AGENTS.md` is the canonical agent entry point. Per its instructions, before any work read
[`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission, ecosystem UML, cross-cutting
disciplines CP-1..CP-5/G6/SEAM, binding engineering conventions in §7, roadmap), the live
[GitHub Project #1](https://github.com/orgs/ContextualWisdomLab/projects/1) (work/roadmap source of
truth), the live gap snapshot [`docs/product-technical-gap-baseline.md`](docs/product-technical-gap-baseline.md)
(not merge authorization; Figma File ID for this repo is N/A), and operate the Project per
[`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md). The standing
autonomous operating directive for the continuous PR review→fix→merge→develop loop across the
ecosystem — the full text a `/goal` session's length-capped pointer refers to — is
[`docs/product-goal-directive.md`](docs/product-goal-directive.md); read it in full before running or
configuring any such loop.
The repo/Project — not private agent memory — is the source of truth. This file complements those
documents; it does not replace them.

## What this repository is

This is the ContextualWisdomLab **organization-wide `.github` special repository**. It has three roles:

1. **Org profile page** — `profile/README.md` (Korean/English lab introduction, DIKW checkpoints,
   project catalog) is what GitHub renders at https://github.com/ContextualWisdomLab. Assets live in
   `profile/assets/`. Org-wide defaults `SECURITY.md`, `.github/CODEOWNERS`, and
   `.github/dependabot.yml` also live here.
2. **Central PR governance and CI hub** — the workflows in `.github/workflows/` are the canonical
   implementation of PR review, security scanning, and merge automation for **every sibling repo**.
   An organization required-workflow ruleset (`CWL Central required workflows`, id `18156473`) runs
   Strix, OpenCode Review, and the PR Review Merge Scheduler from this repo in each target
   repository's context. Repository-local copies of these workflows are drift sources, not
   repo-specific contracts. Central Semgrep binds one job-level `SEMGREP_IMAGE`
   digest for log evidence, `docker manifest inspect`, and `docker run`. See
   `README.md` (policy summary), `docs/pr-review-and-merge-procedure.md`
   (bot/agent procedure), and `PR_GOVERNANCE_AUDIT.md` (live audit + per-repo
   DX/UX transfer decisions).
3. **Infrastructure as code** — `infra/cloudflare/` manages the org's DNS zones and Cloudflare Pages
   hosting declaratively (`zones.json` + `reconcile.sh`, curl + jq only; dry-run by default, writes
   only on explicit manual `mode = apply`).

## Governance model in one paragraph

**OpenCode judges PRs; GitHub Actions performs mechanical updates and merges.** OpenCode approval is
evidence-gated (changed files, CodeGraph evidence, Change Flow DAG, test/coverage/docstring evidence,
an actually-executed PoC via `scripts/ci/sandboxed_verify.py` or `scripts/ci/sandboxed_web_e2e.py`,
split `Developer experience:` / `User experience:` sections). Deterministic
code may repair only trusted `path:line` bindings on LLM probes that already
carry an independent proof and source-line digest; it never invents observed
results. The scheduler updates a PR branch in two cases: after approval, when no current-head check
has failed and GitHub reports the PR as behind; and before review dispatch, when the PR is behind and
no current-head check is still queued or running (an in-flight check is evidence the update would
discard; see #1935). The mechanical merge scheduler itself never synthesizes a fix: it gives `DIRTY`/`CONFLICTING`
PRs repair guidance. A separate edit-capable autofix flow
(`scripts/ci/pr_review_fix_scheduler.py` → `.github/workflows/pr-review-autofix.yml`) may, for an
approved same-repository-head PR, merge the base into the head and resolve the conflict markers; the
resulting head is fully re-reviewed and re-checked before it can merge, so a wrong resolution cannot
merge unreviewed. Old approvals and old checks are not merge evidence after the head SHA changes.
Details: `docs/pr-review-and-merge-procedure.md` and `PR_GOVERNANCE_AUDIT.md`.

## Structure

- `.github/workflows/` — the central workflows. `pull_request_target`-triggered required workflows
  (`opencode-review.yml`, `noema-review.yml`, `pr-review-merge-scheduler.yml`, `strix.yml`, …),
  security gates (`python-security.yml` bandit + pip-audit,
  `security-scan.yml`, `sast-semgrep.yml`, `secret-scan.yml`, `codeql-pr.yml`, `osv-scanner-pr.yml`,
  `scorecard-*.yml`, SBOM workflows), and reusable `workflow_call` workflows sibling repos call
  (`deploy-pages.yml`, `pr-review-fix-scheduler.yml`).
- `scripts/ci/` — Python/bash helpers the workflows execute (schedulers, review normalization and
  gates, sandboxed verification, prompt template rendering). `tests/` covers them.
- `opencode.jsonc` + `ci-review-prompt.md` + `code-reviewer-prompt.md` — the OpenCode reviewer
  configuration (GitHub Models provider, CodeGraph/DeepWiki/Context7/web-search MCP). All reviewer
  agents have `"edit": "deny"`: they are reviewers, never implementers. Keep it that way.
- `requirements-{bandit,pip-audit,strix,opencode-review}-ci.txt` + `*-hashes.txt` — pinned CI
  dependency sets (see below). `requirements-strix-ci-overrides.txt` documents one deliberate
  `uv pip compile --override` (strix-agent's declared `cryptography<49` vs. this repo's
  `cryptography==50.0.0` security pin; see #952) — re-verify it whenever strix-agent bumps again.
- `fuzz/` + `.clusterfuzzlite/` — Atheris fuzz targets for the review-output normalizer and the
  ClusterFuzzLite discovery marker.
- `docs/` — master context, Project protocol, `org-required-workflow-rollout.md`,
  `scorecard-governance.md`, SBOM inventory. Doctoring records live under
  `docs/doctoring/`. [`ARCHITECTURE.md`](ARCHITECTURE.md) is the control-plane
  diagram for review, hourly NVIDIA NIM repair, exact-artifact SBOM attestation,
  and merge trust boundaries.
- `.jules/` — recorded performance (`bolt.md`) and security (`sentinel.md`) learnings from past work
  on `scripts/ci/`; worth scanning before optimizing or hardening those scripts.

## Commands

Run from the repo root. CI installs the exact toolchain with:

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements-opencode-review-ci-hashes.txt
```

Tests, coverage, and docstring gates (`pyproject.toml` sets `pythonpath = ["."]`, coverage source
`scripts/ci` with `fail_under = 100`, and interrogate `fail-under = 100` excluding `tests`):

```bash
coverage run -m pytest tests && coverage report --show-missing
interrogate
```

## Hash-pinned requirements discipline

CI installs Python tools only with `pip install --require-hashes` from the `*-hashes.txt` files.
Never hand-edit a `-hashes.txt` file: edit the top-level `requirements-<tool>-ci.txt` input, then
regenerate with the exact `uv pip compile` command recorded in the hashes file's header comment,
e.g.:

```bash
uv pip compile --generate-hashes --python-version 3.12 --python-platform x86_64-manylinux_2_28 requirements-bandit-ci.txt -o requirements-bandit-ci-hashes.txt
uv pip compile --generate-hashes --python-version 3.12 --python-platform x86_64-manylinux_2_28 requirements-pip-audit-ci.txt -o requirements-pip-audit-ci-hashes.txt
uv pip compile --generate-hashes --python-version 3.13 --python-platform x86_64-manylinux_2_28 --override requirements-strix-ci-overrides.txt --output-file requirements-strix-ci-hashes.txt requirements-strix-ci.txt
./scripts/ci/compile_opencode_review_lock.sh
```

Note the per-file Python versions differ (bandit/pip-audit: 3.12; strix: 3.13; OpenCode
review: 3.14). The OpenCode review generator always passes `--upgrade` so an existing output
file cannot preserve hashes from the previous Python target, and records itself as the lock's
repeatable compile command.

## Conventions and gotchas specific to this repo

- **Contract tests pin workflows AND prose.** `tests/` asserts exact strings and structure of
  `PR_GOVERNANCE_AUDIT.md`, `docs/org-required-workflow-rollout.md`, `opencode.jsonc`, and several
  workflow files (e.g. `test_pr_governance_audit_contract.py`, `test_codeql_pr_workflow_contract.py`,
  `test_opencode_workflow_shell_syntax.py`, `test_opencode_agent_contract.py`). Editing those files
  without running the test suite will break CI.
- **A "superseded" closure is a claim to verify, not accept.** See `AGENTS.md`'s "Verifying a
  'superseded — closing' claim" section. Two traps specific to this repo: use a **three-dot**
  diff (`git diff --stat origin/main...<head>`) — two-dot reports `main`'s own newer commits as
  phantom deletions by a stale PR; and do not use `git merge-base --is-ancestor` as the test,
  because this repo mixes squash merges with real merge commits, so it answers a different
  question than "is this content on `main`". Narrowing a PR into successors is the same claim and
  needs the same evidence.
- **100% coverage and 100% docstrings on `scripts/ci/`** are hard gates, not aspirations. New helper
  code needs matching tests and docstrings.
- **Product hourly callers** stay thin. Do not hard-code OriginWeave, aFIPC, naruon, or Keyverse
  into `pr-review-fix-scheduler.yml`. The model credential remains `NVIDIA_NIM_API_KEY`
  on the worker, never `COPILOT_GITHUB_TOKEN`.
- **Central review routes through the vendored contextual-orchestrator gateway.**
  `pr-review-autofix.yml` provisions `scripts/ci/contextual_orchestrator_review_sidecar.sh`
  (the five provider secrets flow into its KV; the writer runs
  `contextual-orchestrator/orchestrator/free`). Keep the ZDR-first policy and the
  exact-head/vendoring pins in `scripts/ci/zdr_policy.py` and
  `scripts/ci/contextual_orchestrator_review_sidecar.sh` in sync with their contract tests.
- **`pull_request_target` trust boundary.** The required review workflows run the *base branch's*
  trusted scripts. A PR that edits the trusted review workflows can fail its own checks until the
  base branch catches up; a same-head manual `workflow_dispatch` Strix run may supply review evidence
  but does not replace required PR checks. Do not widen a `pull_request_target` job token to
  repository-write permission.
- **Review output must go through the Python normalizer** (`scripts/ci/opencode_review_normalize_output.py`)
  — it escapes `<`, `>`, `&` when embedding JSON in HTML comments to prevent Markdown-comment
  breakout. Do not reintroduce bash fast-path extraction.
- **Cloudflare changes are dry-run by default**; nothing is deleted unless `prune = true` is set
  explicitly. PRs never see the Cloudflare API token.
- **Required workflows ignore `on:` filters.** Org ruleset `18156473` runs the central workflow file
  in each target repository's context and discards its `paths`, `paths-ignore`, `branches`, and
  `types` there (confirmed live: `bandscope` has no local `codeql-pr.yml`/`strix.yml`/
  `security-scan.yml`, yet ruleset-injected runs of all three exist). `.github` is excluded from
  that ruleset and instead uses classic branch protection with 14 named required contexts, where a
  path-filtered workflow leaves its context Pending forever. Never add a trigger-level filter to a
  required workflow; skip at job level via a `changed-scope` gate job instead, and always keep one
  job with no output-dependent `if:` so the run concludes `success` rather than `skipped`. See
  `docs/doctoring/required-workflow-path-filter-boundary.md`.
- **Narrowing a PR does not carry its delta automatically.** When a large PR is split into
  successors, diff the union of the successors against the original before treating the supersession
  as complete — each successor passing its own tests does not prove the union still covers the
  original's scope. `#1871` → `#1877` + `#1879` silently dropped the coverage/docstring delta and
  left the required gate broken on `main` until `#1883`. See AGENTS.md's "Supersession and
  constant-change review".
- **Model-path timeouts are policy-fixed, not an engineering judgment call.** `docs/product-goal-directive.md`
  section 8 accepts that central OpenCode/Strix/Noema may take more than two hours per model and states
  that speed is not a core consideration. `#1889`/`#1890`/`#1892` each added a 900-second cap on genuine
  multi-hour-hang evidence and were all reverted (`#1891`, `#1895`). Fix runner occupancy at the
  admission/continuation boundary instead; never convert elapsed inference time into a model-failure
  verdict.
- **Org-wide binding conventions** (permissive licenses only — verify SPDX before adding anything;
  cross-repo references as `owner/repo#num` or full URLs; durable knowledge in the repo/Project, not
  private memory; one roadmap phase at a time) are defined in `docs/CWL-MASTER-CONTEXT.md` §7 and
  apply here.
- **Agent sessions here share one GitHub identity, so they cannot approve each other's PRs.** Every
  session pushes and reviews as the same account, and GitHub refuses a review with `event=APPROVE` on
  a PR that account authored (`POST /repos/{owner}/{repo}/pulls/{n}/reviews` → 422 "Can not approve
  your own pull request"). This is not a formality to route around: `merge_approval_block_reason` in
  `scripts/ci/pr_review_merge_scheduler_core.py` fails closed unless GitHub's `reviewDecision` is
  `APPROVED` *and* `has_independent_current_head_approval` finds a non-author formal APPROVED review
  on the exact current head. A verification comment documents evidence but satisfies neither
  condition, so a peer session's review cannot unblock a merge — that needs a different identity or
  the documented bypass path. Relatedly, `git log`/`merged_by` cannot attribute work to a session, so
  read the diff before treating an unexplained commit on your branch as an intrusion.
- **`actions/runs?status=completed` is a misleading sample while the queue is churning.** When
  cancelled/skipped runs are produced in bulk, a page of completed runs (default 30, so pass
  `per_page=100`) can contain zero `success`/`failure` results and make the pipeline look dead far
  longer than it is. Querying `status=success` and `status=failure` directly cuts through the churn
  to the most recent real conclusion of each kind. Those are historical signals about pipeline
  liveness only — they never substitute for exact-current-head evidence on the PR you are acting on.
- **Do not assume `interrogate` skips private helpers.** `[tool.interrogate]` here sets no
  `ignore-*` flags and the tool defaults them off, so a docstring-less `_helper` or `__helper` in
  `scripts/ci/` counts against the 100% gate — it is the stricter docstring check, not the laxer
  one. Sibling repositories configure this differently (`contextual-orchestrator` enables six
  `ignore-*` flags and does skip them), so read the target repo's `pyproject.toml` rather than
  carrying a docstring habit across repositories. Note also that `ignore-private` would cover only
  double-underscore names; single-underscore needs `ignore-semiprivate`.
- **A stale PR's conflict scope is a snapshot, not a property of the PR.** Any advance of the base
  between measuring the conflicts and resolving them invalidates the list, and base advances land in
  the same directories conflicts do (`.github/workflows/`, `scripts/ci/`, `docs/doctoring/`). Scope
  grows as often as it shrinks — a branch that merged cleanly can become conflicted with no change
  to the branch at all — so re-run the merge yourself immediately before resolving and treat any
  earlier measurement, including your own from minutes ago, as expired. Resolving against a stale
  smaller scope silently leaves conflicts unhandled.
- **No test parses fenced code blocks.** The doc-contract tests match exact prose in specific files;
  none of them check Markdown structure, and `ARCHITECTURE.md` (five mermaid diagrams) is read by no
  test at all. A conflict resolution that splits a fenced block into two fragments therefore ships
  green, rendering the diagram source as a plain code block. After resolving a conflict in a
  document containing fenced blocks, re-read the whole enclosing section rather than the diff hunk,
  and confirm each block has one opening fence carrying its language tag and one matching closing
  fence. Do not check by counting fences — a split leaves four where there were two, so an even
  count proves nothing. The damage can also arrive inherited, from an earlier commit on the same
  branch or from the autofix flow's conflict-marker resolution.
