# Hyosung Strix consumer admission

Status: Proposed; no runtime authorization or successful cross-organization scan.

The MLLO consumer `HYOSUNG-ITX-AI-Business-Department/llm-gateway-console`
currently uses a local review workflow whose GitHub Models request returned
HTTP 410 (`github_models_retirement_brownout`, run 34690093150, job
103543712323). The central main Strix workflow already selects
`contextual-orchestrator/orchestrator/free`, but its visibility and dispatch
metadata checks reject the Hyosung repository before a governed scan can run.

This change adds exactly that repository to both existing checks. Other Hyosung
repositories remain rejected. The shared review admission controller is not on
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
