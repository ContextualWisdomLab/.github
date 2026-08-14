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

The latest reproduction is run `31702234021` (job `94453926612`) for head
`4d7267b3bf5a90a1fd5a64368bb5c9af33f12234`. GitHub again reported the Strix job
as `success`, but the artifact contained only failed `run.json` files, no
`evidence-binding.json`, and provider failures including NVIDIA NIM `429`, a
GitHub Models `410` retirement brownout, and a context-window overflow. The
executed step list had no provenance-validation step because the
`pull_request_target` run used the trusted base workflow; that base workflow
printed `Treating as a neutral skip` after the fallback attempts were
exhausted. This is not clean security evidence and cannot clear the required
check.

The wrapper now treats any `neutral skip` marker in the captured gate log as
incomplete evidence even when the gate exits zero. The regression contract pins
that marker check. This protects future default-branch runs, while the PR that
introduces the fix still requires a post-merge default-branch
`repository_dispatch` run with a matching `evidence-binding.json`; a green
`pull_request_target` result before that run remains base-workflow evidence only.

After this fix was pushed, central run `31708982141` for the exact head
`e1cfbed814431533ffbe03ba0f33aca671c160da` was cancelled at
`2026-08-13T14:16:42Z` before Strix could produce a report. The same
`pull_request_target` event cancelled the linked required jobs, while the
contextual-orchestrator and fast-mlsirm exact-head jobs remained queued and the
three repository runner APIs reported `0 total / 0 online / 0 busy`. This is
CI-capacity evidence, not a code or security conclusion; no cancelled run may
supersede the required checks or structured-evidence gate.

## Model tool-contract failures (2026-08-14)

Contextual-orchestrator PR #109 exact head
`27aa4ad3dcfbd94ec85fbce40a77955361b877c4` produced a failed Strix run
`31775265809`/job `94689345852` after 884 seconds. NVIDIA NIM Nemotron returned
an agent tool request that the installed Strix agent could not execute:
`agents.exceptions.ModelBehaviorError: Tool execute not found in agent strix`,
with the trusted traceback in `strix/core/execution.py`. No vulnerability
report was produced and publication was skipped.

The trusted gate must preserve this as provider/model execution failure and
incomplete evidence. Central PR #965 adds a bounded classifier requiring both
the exact agent exception and the Strix execution traceback, routes only to a
distinct fallback model, and deliberately does not retry the same model. The
classifier rejects target-source text that merely copies the error wording.
This is not a LibreSSL/TLS diagnosis, a target vulnerability, or a clean scan.

Central run `31776384905` later produced a zero-finding report, but artifact
`9210207198` still lacked `evidence-binding.json` because the
`pull_request_target` execution used the protected base workflow. That result
is provider/content evidence only. A protected-main integration followed by a
default-branch run must still bind repository, full head, run/job, report path,
and digest before any security result can satisfy a merge gate.

## Dependabot alert reconciliation (2026-08-14)

The repository default branch still reports open alerts #5--#9 for `aiohttp`
and `cryptography`, although the manifests already carry the first patched
versions: `aiohttp==3.14.3` and `cryptography==50.0.0` in both Strix
requirements files. The current required Python supply-chain check passes.

Keep the exact pins and hash lock, do not dismiss or suppress these alerts, and
re-fetch the alert manifest and `first_patched_version` after dependency
refreshes until GitHub recomputes the stale alert state. If a refreshed alert
still overlaps an installed version, regenerate the lock and hashes from the
project tooling and rerun the security workflow; never weaken the gate to make
the warning disappear.

## Current-head review remediation (2026-08-14)

The exact-head CodeRabbit review of central PR #965 identified four boundary
issues that remain part of the acceptance contract:

1. A structured `strix` commit status is usable only when its description is
   an exact match, its URL is exactly the configured repository's Actions run
   URL, and the referenced run API object is the same successful
   `repository_dispatch` execution of `.github/workflows/strix.yml` with the
   current head SHA. A description substring, external Actions URL, different
   workflow, or different head is rejected.
2. The gate emits a run-scoped marker prefix before fail-closed or incomplete
   evidence messages. The wrapper matches only that prefix, so untrusted model,
   scanner, or target-source text cannot manufacture a marker or cause a
   false-negative guard.
3. The retained `strix_runs/` tree is scrubbed by the trusted redactor before
   provenance binding and artifact upload. Its minimum-disclosure allowlist
   removes credential shapes, email addresses, phone numbers, IPv4 addresses,
   and absolute runner paths while preserving repository-relative findings and
   exact report digests.
4. Each OpenCode model attempt is launched in a dedicated POSIX session and
   process group. Cleanup therefore cannot skip a child because it inherited
   the review shell's process group; the failed-check artifact download also
   receives `/dev/null` on stdin and its cleanup function returns explicitly.

The corresponding regressions cover the exact URL/run/head/workflow contract,
run-scoped marker detection, evidence redaction, requirements include paths,
and process-group cleanup. These fixes do not create approval authority:
independent review, terminal current-head checks, structured same-head Strix
evidence, resolved threads, and protected merge remain separate gates.

## Structured-status hold must validate the artifact (2026-08-14)

The post-merge hold consumer had a narrower boundary than the failed-check
collector: it verified the `strix` status description, Actions URL, and
`repository_dispatch` run metadata, but it could have released
`WAITING_FOR_POST_MERGE_STRIX_EVIDENCE` without downloading the run's
`strix-reports` artifact. A successful status and run object alone do not prove
that `evidence-binding.json`, the report path, or the report digest exists.

The consumer now downloads the named `strix-reports` artifact and requires the
same current head SHA, run ID, completed scan marker, safe report-relative path,
nonempty report, and SHA-256 digest match used by failed-check supersession.
Missing, mismatched, malformed, or digest-invalid artifacts leave the hold in
place. The contract test covers missing binding, wrong head, wrong run ID,
missing report, and wrong digest cases.

## Artifact identity and outer-run binding (2026-08-14)

The first version of this consumer checked only the artifact name and copied
the provider's `run.json` identifier into `evidence-binding.json`. A provider
run identifier is not the GitHub Actions run identifier in the status URL, and
name-only download is ambiguous if a run exposes duplicate, expired, or stale
artifacts. The workflow now records the target repository, the exact
`strix-reports` artifact name, and the outer `$GITHUB_RUN_ID`; consumers first
require exactly one non-expired artifact with that name, then require all three
binding fields before accepting the report. The provider's internal identifier
remains non-authoritative. Regression coverage rejects missing, duplicate, and
expired artifact listings as well as repository/name mismatches.

## Current exact-head provider/content evidence (2026-08-14)

Central PR #965 exact head
`3a2be84e983f44f4ad584a650f9721223621b52b` produced Strix run
`31777570466`/job `94696182267` with a successful zero-finding report and
artifact `9210803173`. The changed-file materializer retained seven CI/workflow
files, and the report assessed the scanning infrastructure rather than an
application target. The artifact contained no `evidence-binding.json` and the
raw `run.json` had no repository, head, or digest metadata. This is bounded
provider/content and scope evidence only, not proof of a clean PR-head security
scan or merge eligibility. Protected-main integration and a matching structured
binding remain required.

The linked fast-mlsirm PR #816 exact head
`03004b8ca54a6f821109afbc02bca5e7e3f94391` produced Strix run
`31777428325`/job `94695759332` with a successful zero-finding report and
artifact `9210847280`. Its raw `run.json` likewise had null repository/head/
digest fields and the artifact had no `evidence-binding.json`. Preserve this
as provider/content evidence only; do not promote it to a clean security gate
until the hardened workflow is on protected `main` and a post-integration run
verifies the exact repository, full head, run/job, report path, and digest.

Central PR #1009 exact head
`2833d8a1c2f2cbb02387a2af752db51298cc64c4` was rerun as Actions run
`31813452739` attempt 2, Strix job `94912967996`, with artifact `9236314064`.
The artifact's report SHA-256 is
`8d35921b389a7a88d6b03240bfe7283d395318192028e75ddd626561fcc29982` and its
run.json SHA-256 is
`c7e7bd734cfe544d3b5ac4d9eb98572f304f9bdd56f2bcdf4ad974c75081664a`.
The scan completed successfully and reported zero vulnerabilities, but
run.json has null repository/head/commit metadata and the artifact has no
`evidence-binding.json`. This exact result is therefore provider/content and
changed-file-scope evidence only, not a clean protected gate.

This run also confirms a workflow-bootstrap boundary: the
`pull_request_target` job executes the trusted workflow from protected `main`,
while PR #1009's new provenance-validation steps live on the PR branch and
cannot validate that branch's own required run. Do not call the green rerun a
clean self-proof, and do not bypass the boundary with status-only or manual
approval. Keep the PR evidence requirement explicit: after the hardened
workflow is accepted on protected `main`, run a default-branch trusted
`repository_dispatch` scan for the exact target repository, PR head, job, and
report digest, then repeat the independent review and terminal-check gate.

The push response also reported five open Dependabot alerts on the protected
default branch: two high `cryptography` alerts and three medium/high `aiohttp`
alerts. The live alert metadata identifies fixed versions `cryptography 50.0.0`
and `aiohttp 3.14.2`/`3.14.3`, and the PR branch already pins
`cryptography==50.0.0` and `aiohttp==3.14.3` in both Strix requirement files.
Do not dismiss these alerts as stale by assumption: after the dependency fix
is integrated, rerun the dependency/security checks and verify the live alert
state and lock hashes; if any alert remains open, investigate the resolved
manifest before Merge.

The next central PR #1009 exact-head run for
`d22097a35eeba5dd306acce3ebe6b678ae6b75d6` failed closed as run
`31847453432`, job `94916734763`, artifact `9236614384`. Strix reported one
MEDIUM finding in `scripts/ci/redact_sensitive_log.py`; report SHA-256 is
`7fbb058c226b0b70a722634363cb44eb499bb49b9f51adc3c371cf9d6fae7666`,
run.json SHA-256 is
`1cc7caa25946de9a6b5fbb7cef71e3f70e2989fd2403470f60135e1085aed80c`, and
vulnerabilities.json SHA-256 is
`ba714363cdd508a08db8c81b9b3001a18d2b8d293f370143cdc06b09c9323762`.
The finding was reproducible against the PR-head source: JSON values under a
non-sensitive key such as `result` were not passed through the known-token
patterns, and `sk_live_...` was not covered by the provider-token patterns.
The model report's prose saying the issue was already fixed was not accepted
as evidence; the source and proof of concept controlled the decision.

The remediation adds known provider-token patterns, runs the unstructured
credential pass after JSON serialization, and adds exact JSON/assignment
regressions to the trusted Strix contract test. A fresh exact-head Strix run is
required after this source fix; the failed run remains a real security finding,
not a provider flake or a reason to lower the gate.

## References

MITRE. (2026). *CWE-754: Improper check for unusual or exceptional
conditions*. https://cwe.mitre.org/data/definitions/754.html

IEEE. (2008). *IEEE standard for software reviews and audits* (IEEE Std
1028-2008). https://doi.org/10.1109/IEEESTD.2008.4601584
