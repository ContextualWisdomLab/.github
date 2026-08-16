# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read first

`AGENTS.md` is the canonical agent entry point. Per its instructions, before any work read
[`docs/CWL-MASTER-CONTEXT.md`](docs/CWL-MASTER-CONTEXT.md) (mission, ecosystem UML, cross-cutting
disciplines CP-1..CP-5/G6/SEAM, binding engineering conventions in §7, roadmap), the live
[GitHub Project #1](https://github.com/orgs/ContextualWisdomLab/projects/1) (work/roadmap source of
truth), and operate the Project per [`docs/agent-github-project-protocol.md`](docs/agent-github-project-protocol.md).
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
   repo-specific contracts. See `README.md` (policy summary) and `PR_GOVERNANCE_AUDIT.md`
   (live audit + per-repo DX/UX transfer decisions).
3. **Infrastructure as code** — `infra/cloudflare/` manages the org's DNS zones and Cloudflare Pages
   hosting declaratively (`zones.json` + `reconcile.sh`, curl + jq only; dry-run by default, writes
   only on explicit manual `mode = apply`).

## Governance model in one paragraph

**OpenCode judges PRs; GitHub Actions performs mechanical updates and merges.** OpenCode approval is
evidence-gated (changed files, CodeGraph evidence, Change Flow DAG, test/coverage/docstring evidence,
an actually-executed PoC via `scripts/ci/sandboxed_verify.py` or `scripts/ci/sandboxed_web_e2e.py`,
split `Developer experience:` / `User experience:` sections). The scheduler updates a PR branch only
when the latest review is approved, no current-head check has failed, and GitHub reports the PR as
behind. The mechanical merge scheduler itself never synthesizes a fix: it gives `DIRTY`/`CONFLICTING`
PRs repair guidance. A separate edit-capable autofix flow
(`scripts/ci/pr_review_fix_scheduler.py` → `.github/workflows/pr-review-autofix.yml`) may, for an
approved same-repository-head PR, merge the base into the head and resolve the conflict markers; the
resulting head is fully re-reviewed and re-checked before it can merge, so a wrong resolution cannot
merge unreviewed. Old approvals and old checks are not merge evidence after the head SHA changes.
Details: `README.md` and `PR_GOVERNANCE_AUDIT.md`.

## Structure

- `.github/workflows/` — the central workflows. `pull_request_target`-triggered required workflows
  (`opencode-review.yml`, `noema-review.yml`, `pr-review-merge-scheduler.yml`, `strix.yml`,
  `close-empty-pr.yml`, …), security gates (`python-security.yml` bandit + pip-audit,
  `security-scan.yml`, `sast-semgrep.yml`, `secret-scan.yml`, `codeql-pr.yml`, `osv-scanner-pr.yml`,
  `scorecard-*.yml`, SBOM workflows), and reusable `workflow_call` workflows sibling repos call
  (`deploy-pages.yml`, `pr-review-fix-scheduler.yml`).
- `scripts/ci/` — Python/bash helpers the workflows execute (schedulers, review normalization and
  gates, sandboxed verification, prompt template rendering). `tests/` covers them.
- `opencode.jsonc` + `ci-review-prompt.md` + `code-reviewer-prompt.md` — the OpenCode reviewer
  configuration (GitHub Models provider, CodeGraph/DeepWiki/Context7/web-search MCP). All reviewer
  agents have `"edit": "deny"`: they are reviewers, never implementers. Keep it that way.
- `requirements-{bandit,pip-audit,strix,opencode-review}-ci.txt` + `*-hashes.txt` — pinned CI
  dependency sets (see below).
- `fuzz/` + `.clusterfuzzlite/` — Atheris fuzz targets for the review-output normalizer and the
  ClusterFuzzLite discovery marker.
- `docs/` — master context, Project protocol, `org-required-workflow-rollout.md`,
  `scorecard-governance.md`, SBOM inventory. Doctoring records live under
  `docs/doctoring/`. [`ARCHITECTURE.md`](ARCHITECTURE.md) is the control-plane
  diagram for review, hourly NVIDIA NIM repair, and merge trust boundaries.
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
uv pip compile --generate-hashes --python-version 3.13 --python-platform x86_64-manylinux_2_28 --output-file requirements-strix-ci-hashes.txt requirements-strix-ci.txt
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
- **100% coverage and 100% docstrings on `scripts/ci/`** are hard gates, not aspirations. New helper
  code needs matching tests and docstrings.
- **Strix lock:** compile with `scripts/ci/compile_strix_ci_lock.sh` and
  `requirements-strix-ci-overrides.txt`. Install with `--require-hashes --no-deps`.
  Do not let pip re-resolve `cryptography<49`.
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
- **Org-wide binding conventions** (permissive licenses only — verify SPDX before adding anything;
  cross-repo references as `owner/repo#num` or full URLs; durable knowledge in the repo/Project, not
  private memory; one roadmap phase at a time) are defined in `docs/CWL-MASTER-CONTEXT.md` §7 and
  apply here.
