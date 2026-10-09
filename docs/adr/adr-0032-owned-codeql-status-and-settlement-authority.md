---
title: "ADR-0032: Owned CodeQL status and settlement authority"
status: Proposed
date: "2026-09-27"
authors: "Codex"
tags: [architecture, ci, security]
supersedes: ""
superseded_by: ""
---

# ADR-0032: Owned CodeQL status and settlement authority

## Status

Proposed. Requires #2405 complete terminal-proof foundation, owned-app installation permission acceptance, and an unchanged-head live canary before protected deployment is accepted.

## Context

DiskSage #473 dispatch 36305375849 encountered cross-repository HTTP403 during status publication and required-run settlement. Public app and organization installation metadata confirm opencode-agent is owned by anomalyco and has Actions/read and statuses/read. A consumer cannot change the external owner's app permissions. The organization-owned cwl-noema-review (app4291520) is already installed on all repositories with security_events/read; its private-key organization secret is available to central workflows. The existing target-scoped analysis-read token remains the GHAS reader.

## Decision

Use the existing owned Noema app for separate target-repository tokens: statuses/write solely for authenticated CodeQL receipt publication, and Actions/write solely for exact required-run settlement. Keep security_events/read in its existing separate read token. The installation must authorize those two write permissions; credentials cannot mint permissions the installation lacks. Optional mint failures retain existing fallback credentials and never create validation success.

The owned status writer must publish as cwl-noema-review or cwl-noema-review[bot]; another returned creator is rejected. No arbitrary actor is added. Complete base/head/run/source/workflow receipt and terminal SARIF/GHAS proof from #2405 remain prerequisites; do not deploy the new receiver trust before that foundation. Preserve exact-run identity, supersession, rerun budget, SARIF preservation and Medium+ gates.

## Consequences

- POS-001: Removes dependence on an external app owner's unavailable write grants.
- POS-002: Reuses an installed app and keeps analysis, publication and lifecycle tokens separate and target scoped.
- NEG-001: Expands the owned installation's capabilities and therefore the impact of its private-key compromise. Restrict key access and retain the trusted default-branch workflow boundary; never export keys into reviewed source or logs.
- NEG-002: Needs owner-authenticated app settings and installation acceptance plus live verification. Unit contracts do not prove deployment or permission availability.

## Alternatives Considered

- ALT-001: Change the external OpenCode app. Rejected because anomalyco owns that app and its current grants cannot satisfy writes.
- ALT-002: Transfer a user's CLI token into CI. Rejected: broad personal credentials are unnecessary and not copied.
- ALT-003: Bypass identity/receipt checks or synthesize success. Rejected because that removes the security proof.
- ALT-004: Reuse the analysis-read token for mutations. Rejected because its read-only contract must remain unchanged.

## Implementation Notes

- IMP-001: Pin the existing create-github-app-token action and request exactly one target repository and one write permission per writer token.
- IMP-002: Grant Actions/write and Commit statuses/write to the owned app and accept the installation update; do not add Code Scanning writes.
- IMP-003: Accept deployment only after real current-head scan, GHAS identity, receipt creator, one exact run-wide wake and terminal required verdict are verified. References: ContextualWisdomLab/.github#2276, #1929 and #2405.

## References

GitHub. (n.d.). *Create GitHub App token*. https://github.com/actions/create-github-app-token
GitHub. (n.d.). *Choosing permissions for a GitHub App*. https://docs.github.com/en/apps/creating-github-apps/setting-up-a-github-app/choosing-permissions-for-a-github-app
