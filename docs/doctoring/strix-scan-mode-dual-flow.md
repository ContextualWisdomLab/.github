# Strix official scan-mode mapping for dual GitHub / Git Flow

검토 기준일: **2026-08-16**

## Incident

The organization-required Strix workflow always ran Quick. `scripts/ci/strix_quick_gate.sh` already forwarded `STRIX_SCAN_MODE` (default `quick`) as `strix -n -t . --scan-mode $SCAN_MODE`, but `.github/workflows/strix.yml` never set the environment variable. Every current event therefore inherited Quick: `pull_request_target`, `push` to `main`/`develop`/`master`, the Monday 03:00 UTC `schedule`, and `repository_dispatch` type `strix-scan`.

Official Strix CLI modes are only `quick`, `standard`, and `deep` (usestrix/strix `--scan-mode` choices). There is no `normal` alias. Quick is the CI/PR path (minutes). Standard is pre-release / weekly (30 min–1 h). Deep is pre-production (1–4 h). The CLI default is deep; CWL must keep choosing explicitly.

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
| `workflow_dispatch` `scan_mode` | chosen (`quick` / `standard` / `deep`, default `standard`) | Deep only: 360 / 340 / 14400 / 16200 |

`repository_dispatch` remains the default-branch-only, PR-metadata-bound same-head retry. It cannot scan a branch or tag release candidate. The mapping requires `github.event_name == 'push'` before treating `refs/heads/main` or `refs/heads/master` as Standard, because a `repository_dispatch` SHA is the default branch and is often `main`.

`workflow_dispatch` is restored with a single `scan_mode` choice so an incomplete release candidate can be scanned by hand. Deep is allowed only on that manual path. The required PR job stays on the 120-minute budget. Deep uses the GitHub-hosted 360-minute ceiling and leaves about 20 minutes after the 340-minute step for artifact and status publication.

`require_safe_scan_mode` now allowlists `quick|standard|deep` and rejects `normal` and every other string, including charset-valid aliases.

Fail-closed behavior is unchanged: missing artifact, unmapped findings, infrastructure errors, PR scoping, and severity gating stay as they were. The hashed-lock installer line is not part of this change.

`pull_request_target` continues to execute trusted base scripts only.

## Verification contract

`tests/test_strix_scan_mode_policy.py` and `scripts/ci/test_strix_quick_gate.sh` fail if:

1. the event → mode expression is reverted or `repository_dispatch` can select a mode;
2. Deep job/step/process budgets apply to the required PR path;
3. a GitHub release event or RC-tag trigger is added;
4. `require_safe_scan_mode` accepts `normal` or any unofficial name;
5. `workflow_dispatch` grows repository, pull-request, or privileged-retry inputs.

The quality workflow trigger includes this record, the mapping test, and `.github/workflows/strix.yml` so later edits re-run exact-head evidence.

## Rollback

Roll back the mapping and this record together only if a required `pull_request_target` job is observed running Deep or a 360-minute budget. Do not restore unconditional Quick by deleting `STRIX_SCAN_MODE`. Do not invent RC tags to replace the manual `workflow_dispatch` path.

## References (APA 7th)

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

GitHub. (n.d.). *Manually running a workflow*. GitHub Docs. Retrieved August 16, 2026, from https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow

Strix. (n.d.). *Command-line interface* (`--scan-mode` `{quick,standard,deep}`). usestrix/strix. Retrieved August 16, 2026, from https://github.com/usestrix/strix
