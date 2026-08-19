# naruon hourly review-repair caller

검토 기준일: **2026-08-19**

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/naruon`, the email-first knowledge-graph workspace. The
caller runs at minute 11, delegates to the product-neutral central review-fix
scheduler, inspects at most 50 open pull requests targeting protected
`develop`, and dispatches at most one bounded repair per heartbeat.

The caller does not implement review or mutation logic. It keeps naruon
standalone while privileged automation remains in `ContextualWisdomLab/.github`.
The two-hour same-head retry floor prevents duplicate writer pressure when
OpenCode, security checks, or attachment-parser validation outlasts one
heartbeat. Queued checks and missing independent approval remain merge gates;
the repair worker cannot manufacture either result.

## Credential and authority boundary

The caller exposes only `contents: read` and job-scoped `id-token: write`. It
maps `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` explicitly, and never
forwards `NVIDIA_NIM_API_KEY`, `COPILOT_GITHUB_TOKEN`, or `secrets: inherit`.
The reusable scheduler validates the exact target and dispatch authority before
materializing mutation credentials.

## Verification and rollback

Contract tests pin the minute 11 cadence, target repository, `develop` base,
single dispatch, two-hour retry floor, explicit secret scope, and central
quality-workflow path filters. Scheduled execution is the operational
acceptance check; source tests alone do not prove a protected-branch merge.

Rollback removes this caller, its contract test, doctoring, and path-filter
entries. It does not change the reusable scheduler or other product callers.

## APA 7th references

GitHub, Inc. (n.d.). *Events that trigger workflows*. GitHub Docs.
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub, Inc. (n.d.). *Reuse workflows*. GitHub Docs.
https://docs.github.com/en/actions/how-tos/sharing-automations/reuse-workflows

GitHub, Inc. (n.d.). *Automatic token authentication*. GitHub Docs.
https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication
