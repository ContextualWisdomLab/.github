# CodeQL matrix recovery race

Status: local implementation under verification; not merged or deployed.

## Evidence and failure boundary

On 2026-09-08, `.github` PR #2029 head
`eb79481bc1696c63273b6c2ca22b5e34f68d0208` produced two successful scan
statuses in dispatch run `34178442472`. Python job `101912523347` then failed
at the wake step with `The workflow run containing this job is already running
(HTTP 403)`. The actions shard had already requested recovery of required run
`34177963535`. This was not a CodeQL finding or a status publication denial.
Both published statuses were authored by `github-actions[bot]`, which the
required consumer deliberately does not trust as the OpenCode app identity.

The existing test double accepted every POST. On base
`c99d49a86a2728d136d9e3a34a6b82a2c0e84a90`, all 24 dispatch tests passed.
Reproducing GitHub's observed active-run rejection made the parallel-language
test fail while completed-run recovery still passed (1 failed, 1 passed).

## Proposed repair and alternatives

One coordinator follows the complete scan matrix and requests one native
failed-jobs rerun. It validates the live open PR head, exact workflow/run,
terminal run state, and equality of the entire failed-job set with the supplied
CodeQL job identities. An unrelated failure, stale identity, or active run
fails closed without a POST. Scan jobs retain read-only Actions access;
recovery alone needs write access. No polling or extra model invocation is added.

The consumer can read a completed scan job only after the same dispatch run's
validation job succeeds. The coordinator may still be finishing; requiring
the entire dispatch run to finish would introduce a race with the jobs it
just restarted. Admission uses the same terminal-evidence conditions to stop
rescanning both clean results and real findings. Findings remain failed checks.

Rejected alternatives: ignoring 403 loses recovery; repeating per-language
requests races again; sleeping occupies runners without establishing identity;
trusting every status creator weakens the verification boundary. A separate
completion-event workflow adds another event and evidence-transfer contract.

## Verification still required

Run both CodeQL contract modules, broader workflow admission/image contracts,
and current-head hosted checks. Inspect the rendered guidance. Prove one
recovery request for a real multilingual PR and terminal required checks before
claiming rollout. Local fake APIs cannot establish hosted convergence or relief
of the organization-wide 60-job ceiling.

## Reference

GitHub. (n.d.). *REST API endpoints for workflow runs*. Retrieved September 8,
2026, from https://docs.github.com/en/rest/actions/workflow-runs

The documented failed-jobs endpoint restarts failed jobs and their dependent
jobs; therefore the full failed-job set must be validated before calling it.
