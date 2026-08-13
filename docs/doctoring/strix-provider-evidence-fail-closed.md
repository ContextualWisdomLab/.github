# Strix provider failures are incomplete evidence

## Incident

The trusted Strix workflow previously converted a non-zero gate result into a
successful required check when the console contained a provider-unavailable
marker and no parsed vulnerability line. That made a rate limit, provider
retirement response, or missing report indistinguishable from a completed
zero-finding scan.

The failure was observed on the same-head scan for
`ContextualWisdomLab/fast-mlsirm#816` at
`e2480e76dfa2139ab23f8372013681dd2cead46a`: the report artifact said zero
vulnerabilities, while the gate logs recorded NVIDIA NIM `429`, GitHub Models
`410`, and an explicit incomplete-evidence/fail-closed result. The required
check nevertheless reported success because the workflow wrapper neutralized
the non-zero gate exit.

## Decision

The trusted gate remains responsible for bounded retry and fallback. The
workflow wrapper now propagates every non-zero gate result. Provider outages,
timeouts, missing reports, and malformed evidence therefore remain failed
security checks until a clean, current-head scan is available. A successful
check is reserved for a trusted gate exit of zero that did not also print
fail-closed, fail closed, failing closed, incomplete-evidence, or
incomplete evidence text.

CWE-754 (MITRE, 2026) and IEEE 1028 (IEEE, 2008): a zero process exit is
an unusual condition when the same log says the scan is failing closed.
The wrapper must not treat that as a completed security review.

This preserves the security boundary: infrastructure failure may delay a merge,
but it cannot create an unaudited approval signal.

## Active required-workflow boundary (2026-08-13)

The exact-head `ContextualWisdomLab/.github#965` run at commit
`5489c5106123f150a3bd77cfb3759de7de4219b1` exposed a second false-green path.
Run `31681226640`, job `94386887113`, reported `success`, but its downloaded
`strix-reports` artifact contained NVIDIA NIM `429`, GitHub Models `410`,
`No Strix vulnerability report artifact was produced`, and no
`evidence-binding.json`. The job step list also lacked the PR-head
`Validate Strix report provenance` step.

The cause is GitHub execution semantics: `pull_request_target` runs the
workflow YAML from the trusted base/default branch. Its PR-head materialization
is data-only input for the trusted smoke test; it does not execute the PR-head
workflow wrapper. Therefore a workflow-changing PR cannot use its own
pull-request run as proof that the new wrapper is active.

The remediation is now explicit. The status publisher uses the distinct
description `Default-branch repository_dispatch Strix structured evidence
binding passed`, and the OpenCode approval path holds a workflow-changing PR
until that exact same-head status exists. After the workflow PR is merged by the
normal protected-branch process, a new default-branch `repository_dispatch`
run must produce a matching `evidence-binding.json` before the result is called
clean. The observed run above is inconclusive and must not be used as approval
evidence.

The same boundary was reproduced on the current exact head of PR #965. Run
`31696985802` (job `94436969831`) reported `success` for head
`b8695c534cf15a2227d92f942dcce3c653276393`, but the downloaded
`strix-reports` artifact had no `evidence-binding.json`, no provenance-validation
step, one `completed` `run.json` without head/commit metadata, and three failed
`run.json` files. Its gate log also contained NVIDIA NIM `429`, GitHub Models
`410` retirement-brownout, `failing closed`, and `No Strix vulnerability
report artifact was produced` markers. Because this was again the trusted
base workflow selected by `pull_request_target`, the green job is
inconclusive base-workflow evidence, not proof that the PR-head provenance
change ran. It must not be used to clear the required security check; only a
post-merge/default-branch `repository_dispatch` run with a matching structured
binding and clean provider evidence can establish completion.

The provenance step also fails closed when `scan-head-sha.txt` exists but
does not match the evidence head SHA. A scan started on a different commit
cannot be published as current-head evidence.

A completed successful `run.json` with no `head_sha` or `commit_sha` (including
nested `scan_results` fields) is also incomplete evidence. The wrapper
previously substituted the scan-start SHA for that missing binding. That let a
copied or metadata-less report publish as current-head evidence. Provenance now
skips those candidates. Only a `run.json` that itself carries a matching head
SHA can pair with `penetration_test_report.md`.

The failed-check evidence collector follows the same rule. A generic successful
check-run or workflow-run is not sufficient to supersede a stale Strix failure;
the collector accepts only a downloaded `strix-reports` artifact whose binding
matches the current head and run ID, whose report exists, and whose SHA-256
digest matches the binding. If that artifact cannot be downloaded or verified,
the failed check remains active.

The same fail-closed rule applies to status supersession. A previous
`current_head_manual_strix_success_status` implementation fell back to any
same-head `repository_dispatch` run whose API result said `completed/success`.
That run result is not proof that the structured artifact was bound to the
head, run ID, and report digest, so it could recreate a false-green path.
The fallback was removed; only the explicit structured status description can
supersede a stale Strix context. The contract tests reject reintroduction of
the unbound fallback.

## References

MITRE. (2026). *CWE-754: Improper check for unusual or exceptional
conditions*. https://cwe.mitre.org/data/definitions/754.html

IEEE. (2008). *IEEE standard for software reviews and audits* (IEEE Std
1028-2008). https://doi.org/10.1109/IEEESTD.2008.4601584
