# Noema startup evidence for contextual-orchestrator PR #1218

On 2026-09-27, run `36025318452`, attempt 3, job `108389560765`
was inspected at consumer head `2fed942d378cd959250f648a16b35276279c9603`.
The job used gateway pin `767e67fbc6b881a452761f32abb69b9971b9b03b`.
Dependencies installed successfully. At 2026-09-26T12:37:08Z the sidecar
started; no health/preflight-ready confirmation followed. The job was cancelled
at 18:35:14Z, approximately six hours after admission. This does not establish
that a Noema review request or any particular provider attempt occurred.

Artifact `10877250808` was created on 2026-09-25T17:04:14Z and belongs to an
earlier attempt. It must not be attributed to attempt 3 merely because the
workflow run ID and consumer head are equal.

The workflow uploaded its two existing sanitized evidence files only under
`failure()`. Using `always()` preserves those same files after successful,
failed and normally cancelled execution, without collecting raw provider logs.
The pinned uploader, file allowlist, five-day retention and absent-file behavior
remain intact. A hard runner timeout may prevent cleanup/upload entirely; this
change cannot recover the missing attempt-3 evidence or prove its internal
startup cause. Gateway inference timeouts must not be invented to hide it.

Verification: the changed workflow contract fails on the previous source;
the Noema workflow contract suite and actionlint verify the revised step.
Hosted execution and independent review remain required before integration.
