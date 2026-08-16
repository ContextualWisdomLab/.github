# Strix official scan-mode mapping for dual GitHub / Git Flow

근거 기준일: **2026-08-16**

## Incident

The organization-required Strix workflow always ran Quick. `scripts/ci/strix_quick_gate.sh` already forwarded `STRIX_SCAN_MODE` (default `quick`) as `strix -n -t . --scan-mode $SCAN_MODE`, but `.github/workflows/strix.yml` never set the environment variable. Every current event therefore inherited Quick: `pull_request_target`, `push` to `main`/`develop`/`master`, the Monday 03:00 UTC `schedule`, and `repository_dispatch` type `strix-scan`.

Official Strix CLI modes are only `quick`, `standard`, and `deep` (Strix, n.d.-a). There is no `normal` alias. Quick is the CI/PR path (minutes). Standard is pre-release / weekly (30 min–1 h). Deep is pre-production (1–4 h) and is the CLI default; CWL must keep choosing explicitly so required PR evidence never inherits Deep.

The previous 120 / 100 / 90 / 95-minute budget is honest for Quick and Standard. It cannot finish Deep. GitHub-hosted jobs max out at 360 minutes.

## Decision

ContextualWisdomLab runs both GitHub Flow (`main`/`master` is the base) and Git Flow (`develop` is the base). That dual-flow setup is incomplete: there is no consistent RC-tag, prerelease, or GitHub `release` event convention, and RankWeave forbids prerelease GitHub Releases. This change therefore does **not** invent `release:` or `v*-rc*` triggers.

Confirmed event → official mode mapping:

| Event | Mode | Job / step / process / total |
|---|---|---|
| `pull_request_target` | `quick` | 120 / 100 / 5400 / 5700 |
| `repository_dispatch` `strix-scan` | `quick` | 120 / 100 / 5400 / 5700 |
| `push` to `develop` | `quick` | 120 / 100 / 5400 / 5700 |
| `push` to `main` or `master` | `standard` | 120 / 100 / 5400 / 5700 |
| `schedule` (Monday 03:00 UTC) | `standard` | 120 / 100 / 5400 / 5700 |

`repository_dispatch` remains the default-branch-only, PR-metadata-bound same-head retry. It cannot scan a branch or tag release candidate. The mapping requires `github.event_name == 'push'` before treating `refs/heads/main` or `refs/heads/master` as Standard, because a `repository_dispatch` SHA is the default branch and is often `main`.

Deep is **not** selected on this privileged workflow. Restoring `workflow_dispatch` on `.github/workflows/strix.yml` would let a writer choose a feature-branch workflow revision. That revision supplies the YAML—`id-token: write` plus `statuses: write` for the `strix` commit-status context—before any in-job trusted-source checkout can run (GitHub, n.d.-b; National Institute of Standards and Technology, 2022). A malicious or confused branch could skip the scan and publish a fake passing `strix` status. The same class of defect already failed `test_no_central_workflow_exposes_branch_selected_manual_dispatch` when `workflow_dispatch` was added to the quality job (see `docs/doctoring/strix-legal-git-paths.md`).

Do **not** restore `workflow_dispatch` on this file as an RC convenience. Do **not** add `client_payload.scan_mode` to the privileged `strix-scan` retry. A later Deep path must be a separately reviewed default-branch-only dispatcher that treats target repository, pull-request number, and exact head SHA as untrusted bounded data.

`require_safe_scan_mode` allowlists `quick|standard|deep` and rejects `normal` and every other string, including charset-valid aliases. The gate may still accept `deep` for local or future dispatcher use; this workflow never sets it.

Fail-closed behavior is unchanged: missing artifact, unmapped findings, infrastructure errors, PR scoping, and severity gating stay as they were. The hashed-lock installer line is not part of this change.

`pull_request_target` continues to execute trusted base scripts only.

## Verification contract

`tests/test_strix_scan_mode_policy.py` and `scripts/ci/test_strix_quick_gate.sh` fail if:

1. the event → mode expression is reverted or `repository_dispatch` can select a mode;
2. Deep job/step/process budgets appear on the required PR path;
3. a GitHub release event, RC-tag trigger, or `workflow_dispatch` is added to this privileged file;
4. `require_safe_scan_mode` accepts `normal` or any unofficial name;
5. `client_payload.scan_mode` or `github.event.inputs.scan_mode` appears in `strix.yml`.

The quality workflow trigger includes this record, the mapping test, and `.github/workflows/strix.yml` so later edits re-run exact-head evidence.

## Rollback

Roll back the mapping and this record together only if a required `pull_request_target` job is observed running Deep or a 360-minute budget. Do not restore unconditional Quick by deleting `STRIX_SCAN_MODE`. Do not restore `workflow_dispatch` on this file to recover Deep.

## Next operator action

Merge this mapping after current-head quality, security, and review evidence pass. If a buyer needs a pre-production Deep scan, open a separate default-branch-only dispatcher design; do not add inputs to `strix.yml`.

## References (APA 7th)

GitHub. (n.d.-a). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (n.d.-b). *Manually running a workflow*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

MITRE. (n.d.). *CWE-345: Insufficient verification of data authenticity*. Retrieved August 16, 2026, from https://cwe.mitre.org/data/definitions/345.html

National Institute of Standards and Technology. (2022). *Secure software development framework (SSDF) version 1.1: Recommendations for mitigating the risk of software vulnerabilities* (NIST Special Publication 800-218). https://doi.org/10.6028/NIST.SP.800-218

Strix. (n.d.-a). *Scan modes*. Strix Docs. Retrieved August 16, 2026, from https://docs.strix.ai/usage/scan-modes

Strix. (n.d.-b). *Command-line interface*. usestrix/strix. Retrieved August 16, 2026, from https://github.com/usestrix/strix
