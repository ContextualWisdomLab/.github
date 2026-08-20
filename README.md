# Contextual Wisdom Lab

Organization special repository for **맥락지혜 연구실 / Contextual Wisdom Lab**.

This repository is the org profile source and the central required-workflow
source. It is not naruon and it does not own product data. It runs alone.
Sibling product repositories consume it by inheriting the organization
required workflows; they do not copy workflow files from here.

The public GitHub organization profile lives in
[profile/README.md](profile/README.md) and is what GitHub renders at
https://github.com/ContextualWisdomLab. Homepage:
https://contextualwisdomlab.github.io/

Bot and agent PR-review procedure (exact-head CI, successor heads,
do-not-merge / `DIRTY`–`CONFLICTING` repair, writer boundaries, approve-gate)
is in [docs/pr-review-and-merge-procedure.md](docs/pr-review-and-merge-procedure.md).

## What this repository is

Three operator-facing roles:

1. **Org profile and public introduction assets.** `profile/README.md` plus
   `profile/assets/` are the lab page. Org-wide defaults `SECURITY.md`,
   `.github/CODEOWNERS`, and `.github/dependabot.yml` also live here.
2. **Central required-workflow source.** Workflows under `.github/workflows/`
   are the canonical PR review, security scan, and merge-automation
   implementation for sibling repositories. Organization ruleset
   `CWL Central required workflows` (id `18156473`) runs those workflows in
   each target repository's context. Repository-local copies are drift
   sources, not repo-specific contracts.
3. **Infrastructure as code for org DNS and Pages.** `infra/cloudflare/`
   manages zones and Cloudflare Pages hosting with `zones.json` and
   `reconcile.sh` (curl + jq only). Dry-run is the default; writes happen
   only on an explicit manual `mode = apply`. Pull requests never see the
   Cloudflare API token.

Naruon is the composition hub that can receive other CWL products. That is
the platform job, not a defect of this repository. This control plane still
shows an independent run: profile, required workflows, and Cloudflare
reconciliation do not require naruon to be present, imported, or running.

## 따로, 또 같이

Every CWL component is standalone and also composable. For this repository
that means:

| Mode | What happens |
| --- | --- |
| **따로 (this repo alone)** | Clone, test, and operate `.github` as the org profile and workflow source. Local quality gates, Cloudflare dry-run, and this repository's own PRs do not depend on naruon or any sibling product checkout. |
| **또 같이 (siblings call it)** | A sibling enables the org required-workflow ruleset (already `repository_name.include=["~ALL"]` with `.github`, `IRT-bibliography-set`, and `noema` excluded, plus `ref_name.include=["~ALL"]`). GitHub runs the trusted workflows from `ContextualWisdomLab/.github@main` in every non-excluded sibling repository branch, including stacked PR base branches. Optional reusable callers (`deploy-pages.yml`, `pr-review-fix-scheduler.yml`) are `workflow_call` entry points, not files to copy. |

Do not copy Strix, OpenCode, Noema, or scheduler workflow files into a
sibling to "satisfy CI." Thick downstream sync PRs are an anti-pattern
unless they are a temporary rollback bridge.

## Current status

Live work and roadmap live on
[GitHub Project #1](https://github.com/orgs/ContextualWisdomLab/projects/1).
The narrative brief is [docs/CWL-MASTER-CONTEXT.md](docs/CWL-MASTER-CONTEXT.md).
The last checked-in ruleset ledger is
[docs/org-required-workflow-rollout.md](docs/org-required-workflow-rollout.md)
(updated 2026-08-21 KST).

Checked-in operator facts:

- Ruleset `18156473` is **active**. It targets every non-excluded repository
  branch (`repository_name.include=["~ALL"]`, exclusions `.github`,
  `IRT-bibliography-set`, and `noema`, and `ref_name.include=["~ALL"]`),
  including stacked pull-request base branches, and sources workflows from
  this repository at `refs/heads/main`.
- Active required workflow paths: `close-empty-pr.yml`, `noema-review.yml`,
  `opencode-review.yml`, `pr-review-merge-scheduler.yml`,
  `security-scan.yml`, `strix.yml`, and `sast-semgrep.yml`.
- This repository itself is GitHub Flow on `main`. It is the central source,
  so it keeps the workflow files; siblings should not.
- Public profile, DIKW checkpoints, project catalog, and the existing APA 7th
  DIKW citations stay in [profile/README.md](profile/README.md#references).
- Control-plane trust boundaries and the hourly NVIDIA NIM repair gate are
  diagrammed in [ARCHITECTURE.md](ARCHITECTURE.md).

If live organization ruleset inspection reports a different ref or a missing
required workflow path, treat that as operations drift and restore ruleset
`18156473` to the current `main` head. Do not compensate by copying
workflows into siblings.

## How a sibling consumes the central workflows

1. Confirm the repository is in the ContextualWisdomLab organization. New
   public repositories inherit ruleset `18156473` without a name-list update.
2. Keep product, build, release, and repo-specific security workflows local.
   Do not add local copies of OpenCode, Strix, Noema, or the merge scheduler.
3. On each pull request, including stacked pull requests targeting a feature
   branch, GitHub creates the required checks in
   the sibling context. Review judgment stays with OpenCode (and the
   independent Noema reviewer). Mechanical branch update and merge stay with
   GitHub Actions in that sibling context, using the configured central
   mutation credential.
4. Optional: call a reusable workflow instead of copying it.

```yaml
jobs:
  deploy:
    uses: ContextualWisdomLab/.github/.github/workflows/deploy-pages.yml@main
    with:
      project_name: example-marketing
      build_dir: ./public
    secrets: inherit
```

5. If a repository cannot inherit the ruleset (for example a public fork
   still onboarding), add a **thin caller** that passes PR number, base
   ref/SHA, head ref/SHA, and inherited secrets into this repository. Do not
   paste the scheduler or review implementation. Thin callers must not define
   a matching scheduler concurrency group.

Private-repository onboarding and fork capability gates are recorded in
[PR_GOVERNANCE_AUDIT.md](PR_GOVERNANCE_AUDIT.md). A public fork can be
governed by the same reusable workflow if it opts in; an external PR head can
still be non-mutable at runtime. The scheduler decides from observed PR
permissions and current-head evidence, not from the repository `fork` flag
alone.

## How to run and maintain this repository alone

From the repository root, after installing the hash-pinned OpenCode review
toolchain:

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements-opencode-review-ci-hashes.txt
coverage run -m pytest tests && coverage report --show-missing
interrogate
```

`pyproject.toml` sets `pythonpath = ["."]`, coverage source `scripts/ci`
with `fail_under = 100`, and interrogate `fail-under = 100` excluding
`tests`.

Hash-pinned CI sets are regenerated from the un-hashed `requirements-*-ci.txt`
inputs with the `uv pip compile` command recorded in each `*-hashes.txt`
header. Do not hand-edit a hashes file. Cloudflare reconciliation stays
dry-run unless an operator runs the workflow with `mode = apply`.

Contract tests pin workflow structure and governance prose
(`PR_GOVERNANCE_AUDIT.md`, `docs/org-required-workflow-rollout.md`,
`opencode.jsonc`, and several workflow files). Edit those files only with the
test suite.

## Related documents

| Document | Role |
| --- | --- |
| [profile/README.md](profile/README.md) | Public org profile, DIKW checkpoints, project catalog, APA 7th references |
| [docs/pr-review-and-merge-procedure.md](docs/pr-review-and-merge-procedure.md) | Bot/agent review, exact-head, successor-head, and merge procedure |
| [PR_GOVERNANCE_AUDIT.md](PR_GOVERNANCE_AUDIT.md) | Live audit and per-repo DX/UX transfer decisions |
| [docs/org-required-workflow-rollout.md](docs/org-required-workflow-rollout.md) | Ruleset `18156473` ledger and sibling onboarding |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Control-plane diagram and trust boundaries |
| [docs/CWL-MASTER-CONTEXT.md](docs/CWL-MASTER-CONTEXT.md) | Mission, ecosystem, and naruon-as-platform brief |
| [docs/agent-github-project-protocol.md](docs/agent-github-project-protocol.md) | How agents operate Project #1 |
| [infra/cloudflare/README.md](infra/cloudflare/README.md) | DNS/Pages reconcile and reusable Pages deploy |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |
