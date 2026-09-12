# Hyosung Strix consumer admission

Status: Proposed; no runtime authorization or successful cross-organization scan.

The MLLO consumer `HYOSUNG-ITX-AI-Business-Department/llm-gateway-console`
currently uses a local review workflow whose GitHub Models request returned
HTTP 410 (`github_models_retirement_brownout`, run 34690093150, job
103543712323). The central main Strix workflow already selects
`contextual-orchestrator/orchestrator/free`, but its visibility and dispatch
metadata checks reject the Hyosung repository before a governed scan can run.

This change adds exactly the console repository and its UI owner
`HYOSUNG-ITX-AI-Business-Department/llm-gateway-console-design` to both existing
checks. The design owner supplies the MLLO navigation surface; reviewing its
change is required for the key-management UI integration. Other Hyosung
repositories and similarly prefixed names remain rejected. The shared review admission controller is not on
this workflow's direct path and is unchanged. No credentials, installation
permissions, provider routes, review verdicts or branch rules are changed.
Existing live PR base/head comparison, private-target handling and separated
status credentials remain mandatory. An allowlisted name is not proof of access.

The extracted workflow regexes failed both regression cases before the change.
After the change, 97 focused tests and one subtest passed, including repository
visibility, orchestrator, queue and documentation-only admission contracts;
actionlint passed. These tests do not prove target App installation, cross-org
read/status permissions, private-target ZDR or a valid current-head scan.

Before adoption, independently review and merge the owner change, establish the
existing scoped credential's target access without exposing its value, and run
one exact-revision dispatch. Require matching source/base/head and authoritative
review evidence before replacing the consumer's local workflow. Do not broaden
an App installation, copy central source, suppress failed checks or treat a
successful dispatch response as completed review. If access is unavailable,
retain the failed/incomplete integration state and repair the owner capability.
Rollback removes this exact consumer alternative from both checks; it does not
revoke or alter any credential. No dispatch has been sent by this change.

## Design-owner extension

Both extracted shell admission expressions rejected the exact design-owner
repository before this extension (two RED cases). The extension admits only the
optional literal `-design` suffix, retaining anchored owner/name matching.
Tests reject extra suffixes, paths, trailing newlines, and another owner.

OpenCode remains a separate integration gap: the current dispatch workflow
rejects non-ContextualWisdomLab targets at its metadata guard, and the required
caller has the same organization restriction. The dispatch-target inventory also
lacks both Hyosung consumers. Strix admission does not repair those boundaries
or establish App installation/read/status authority; no OpenCode adoption or
cross-organization scan is claimed by this change.
