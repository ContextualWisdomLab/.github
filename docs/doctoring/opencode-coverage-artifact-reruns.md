# OpenCode coverage artifact reruns

## Customer-operability decision

OpenCode coverage now accepts only the immutable artifact identifier emitted by
`actions/upload-artifact` in the current GitHub Actions workflow attempt. The
producer exports both that identifier and `github.run_attempt`; the
credential-free coverage consumer checks that the producer attempt equals its
own attempt before downloading by ID.

This closes an evidence-integrity gap in failed-jobs-only reruns. GitHub can
reuse successful job outputs from the earlier attempt, while artifacts can be
expired or unavailable independently. A static artifact name therefore cannot
prove that coverage inspected the exact source produced for the current
attempt. Missing, malformed, expired, or prior-attempt evidence now fails
closed and tells an operator to use a full rerun or a fresh repository
dispatch. The existing one-day retention window remains bounded; no lookup or
fallback to an earlier attempt is permitted.

## Verification and rollback

Repository tests parse the complete producer and consumer job blocks. They
require the attempt-scoped artifact name, immutable upload output, current
attempt comparison, exact-ID download, credential-free consumer permissions,
and actionable recovery message. The central workflow's ordinary full quality
gate exercises the new contract at 100% statement, branch, and docstring
coverage.

Rollback is a normal revert of the workflow, contract test, and fallback-scope
entry. Operators must not restore name-based or prior-attempt artifact lookup;
until a replacement contract is available, a missing producer must continue to
fail closed.

## References

GitHub. (n.d.). *Re-running workflows and jobs*. Retrieved August 24, 2026,
from https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs

GitHub. (n.d.). *REST API endpoints for GitHub Actions artifacts*. Retrieved
August 24, 2026, from
https://docs.github.com/en/rest/actions/artifacts?apiVersion=2026-03-10

GitHub. (n.d.). *upload-artifact* [Computer software]. Retrieved August 24,
2026, from https://github.com/actions/upload-artifact/blob/main/README.md
