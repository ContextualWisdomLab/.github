# All-self-hosted workflow routing — staged rollout

## Authority and scope

On October 3, 2026, the user directed this SDP workstream: “self hosted runner로 모두 전환”. This change covers every runner declaration in the central `.github` repository (73 jobs) and SDP (4 jobs). It does not claim migration of unrelated ecosystem repositories or deployment of runner infrastructure.

## Routing and isolation

Existing restricted control, CodeQL and OpenCode groups stay intact. Existing exact-main workflow predicates and repository predicates stay intact; only their GitHub-hosted fallback changes. Ordinary jobs and non-main fallbacks require all labels `self-hosted`, `linux`, `x64`, `cwlab-ci-isolated`. The new label is a provisioning contract, not a claim that a suitable runner already exists. Never apply it to a privileged control/review runner merely to release queued PR jobs.

PR code must execute on disposable, job-isolated machines without production credentials, privileged Docker sockets, internal-network access or state shared with trusted control jobs. Rebuild the job environment after each job. Secret-bearing trusted jobs need separate disposable instances from untrusted PR jobs; a generic label alone does not attest that separation. Keep current token permissions, environment approvals, immutable artifact checks, exact-head review and required merge gates. This patch does not widen runner-group allowlists, register runners, alter secrets or bypass protection.

R reusable jobs preserve the caller's entire R-version matrix. The OS image input is translated to a self-hosted OS label (`linux`, `windows`, `macOS`) while retaining x64, the isolation label and the original matrix image as an additional custom label. Unknown OS strings select `unsupported-os`, not Linux. Unsupported or unavailable platforms remain queued rather than silently becoming Linux or GitHub-hosted runs. A self-hosted Linux machine must be provisioned with Ubuntu 24.04-compatible userspace and existing CI dependencies; labels do not install packages.

## Actual admission observation and rollout prerequisite

The complete organization runner inventory read during preparation had 9 runners: 7 online Linux x64 and 2 offline. None carried `cwlab-ci-isolated`; no registered Windows or macOS runners were observed. Existing groups contain privileged or workflow-restricted runners. Therefore this configuration is not runtime-ready and must not be enabled or merged before the authorized runner operator provides disposable isolated capacity and verifies repository access. The OpenCode group's sole runner `cwlab-s1-04` was offline; changing fallback routing does not repair it.

Before promotion, the operator must return real runner identity/group/access records, demonstrate isolated cleanup and tool availability, and produce a successful canary job plus every exact-head required gate. Provisioning and runtime canaries are not completed by local YAML parsing or pytest. Preserve existing current-head executions; do not cancel or duplicate model reviews. Ship through normal reviewed protected PRs only, after prerequisites are satisfied.

## Verification and rollback

Permanent regression tests enumerate declarations, reject every GitHub-hosted fallback and keep PR-executing jobs outside privileged pools. Existing workflow-contract assertions are migrated rather than deleted. A structured YAML inventory verifies all 77 central/product job declarations; normal test suites and immutable source comparisons are separate evidence. Rollback is an ordinary reviewed revert of the migration PRs, not a protection change or runner relabeling.

## Primary sources (APA 7)

GitHub. (n.d.). Choosing the runner for a job. GitHub Docs. Retrieved October 3, 2026, from https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job

GitHub. (n.d.). Self-hosted runners reference. GitHub Docs. Retrieved October 3, 2026, from https://docs.github.com/en/actions/reference/runners/self-hosted-runners

GitHub. (n.d.). Using self-hosted runners in a workflow. GitHub Docs. Retrieved October 3, 2026, from https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/use-in-a-workflow
