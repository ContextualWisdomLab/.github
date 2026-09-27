# Persistent runner workspace reuse

## Observed failures

On 2026-09-27, CodeQL scan job 108599677231 on `cwlab-s1-03`
failed with `remote origin already exists` before analysis. The manual Git
initialization reused a repository from an earlier job. Anonymous OpenCode
coverage materialization used the same pattern with `trusted-source` and
also failed a real local repeated-workspace regression.

The subsequent cross-repository status publication returned HTTP 403.
Live organization installation metadata shows `opencode-agent` has only
`statuses: read`. Adding `statuses: write` to the workflow cannot elevate
that installation permission. Existing successful-scan artifact settlement
remains the supported authenticated fallback; this repair does not invent
a trusted status author or widen application permissions.

Scheduler job 108601462359 failed with `invalid UTF-8 string` on the first
GraphQL page. Its query is ASCII; the next same-source job 108601744765
succeeded, and a current read-only request for the same 25-PR page succeeds.
No encoding mutation is justified by this non-reproducing observation.

## Repair

Use the repository's pinned native checkout action for CodeQL's validated
repository and exact head, with cleanup and without persisting credentials.
For anonymous OpenCode coverage bootstrap, discard only the current job
workspace contents after verifying it is not a symlink, matches the physical
current directory, and is directly under the runner-provided job directory.
The directory itself remains. Old Git hooks, configuration, and untracked
files cannot survive this anonymous bootstrap; child symlink targets and
sibling directories remain untouched. The Git fetch stays anonymous and
pinned to the validated trusted source ref.

## Verification

Before repair, three focused regressions failed: repeated anonymous checkout,
linked workspace refusal, and the native CodeQL checkout contract.
After repair, the focused real-Git regressions and existing CodeQL, OpenCode
shell, coverage toolchain, and paired workflow blob contracts report
**105 passed, 1 skipped**. Actionlint validates the two modified workflows
with ShellCheck and Pyflakes disabled; no claim about those engines is made.
Hosted execution and downstream CodeQL analysis are separate acceptance
steps. No active runner is restarted and no unrelated working copy is cleaned.
