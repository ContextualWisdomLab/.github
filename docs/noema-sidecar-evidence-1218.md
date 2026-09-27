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
# Startup progress follow-up for CO #1083

ContextualWisdomLab/contextual-orchestrator#1209 run `36138543702`, job
`108153123179`, logged sidecar start at 19:11:54Z on 2026-09-25, then runner
shutdown at 23:12:37Z without readiness confirmation. The run's artifact API
returned no artifacts. This proves loss of startup evidence, not a particular
provider deadlock or a model failure.

The shared readiness loop now logs every 60 failed health polls whether its
discovery, catalog, policy, and preflight report files are nonempty. These are
presence observations only: no report content, provider response, or credential
is printed. Poll count is not elapsed time and does not impose an inference
deadline. A successful health check still ends the loop, and sidecar process
exit retains the existing failure handling.

The executable regression runs the real health loop with absent, partially
completed, and completed report stages; verifies exact output and secret
non-disclosure; and verifies readiness can succeed after the diagnostic. It
does not establish that the unknown startup cause is repaired. A fresh hosted
run after protected integration is still needed to locate that cause.
