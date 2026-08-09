# Automation control-plane security

Status: active_pr

## Security objectives

The control plane preserves source integrity, least privilege, evidence provenance, reviewer independence, credential confidentiality, and fail-closed merge/release decisions while continuing unrelated safe work.

## Trust boundaries

1. Pull-request source, titles, bodies, comments, patches, artifacts, logs, and model prompts are untrusted.
2. A workflow is trusted only when its source repository and immutable revision are established independently of PR-controlled input.
3. GitHub checks, commit statuses, formal reviews, model outputs, merge authority, release authority, and runtime acceptance are distinct channels.
4. Repository tokens, GitHub Apps, OIDC identities, and model credentials have separate purposes and cannot substitute for one another.
5. Leaf repositories may supply bounded inputs but cannot self-enable privileged central policy.

## Credential contract

- Deterministic gates run before model credentials are required or materialized.
- Reusable workflows declare named minimal secrets; blanket `secrets: inherit` is rejected unless a separately reviewed interface proves every inherited value necessary.
- Autonomous model development uses `NVIDIA_NIM_API_KEY`; `COPILOT_GITHUB_TOKEN` is not a development-model credential.
- OIDC exchanges validate audience, issuer, repository/ref claims, expiry, and the documented response envelope without logging tokens.
- Provider credentials are passed only to the child process that calls that provider and are absent from arguments, reports, summaries, and artifacts.

## Source and evidence integrity

Writes bind exact branch head, target blob/ref, and independently resolved live base. Stale PR base metadata, synthetic merge commits, predecessor runs, skipped required checks, and status-only reviewer text cannot authorize a write or merge.

## Supply-chain and execution controls

Actions and trusted bootstrap inputs use immutable pins and verified hashes where practical. PR-controlled execution runs tokenless, with bounded filesystem access, output limits, timeouts, process-group cleanup, and network denial unless an explicit reviewed operation requires egress.

## Rollback

Disable the narrow caller or revert the exact protected-main integration commit. Preserve evidence, revoke affected credentials, cancel only obsolete runs, and reopen the incident until a current protected-main consumer proves recovery.
