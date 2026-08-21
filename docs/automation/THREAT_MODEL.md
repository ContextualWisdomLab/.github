# Threat model — CWL automation control plane

Status: accepted baseline
Last reviewed: 2026-08-09
Method: repository-scoped asset/entry-point analysis with STRIDE categories and abuse-case validation

## 1. Overview

`ContextualWisdomLab/.github` is the organization automation control plane. Its runtime surfaces are GitHub Actions workflows, helpers under `scripts/ci/`, organization and repository rulesets, GitHub API objects, workflow artifacts, review/model providers, and thin consumers in product repositories. It reads attacker-influenced pull-request and provider data, produces review and security evidence, and can request privileged branch, review, status, or merge operations.

The primary security objective is to keep untrusted product source and evidence useful without allowing either to acquire trusted workflow, credential, human-review, or merge authority. This model covers the repository-wide control plane rather than one pull request or current diff. Intended controls and current implementation are not interchangeable: the exact implementation and test status for each threat is recorded in §7, and open gaps remain non-authorizing.

Product application runtimes and their domain data are outside this repository's primary runtime. They matter here only when a central workflow receives their source, metadata, logs, credentials, or mutation authority.

## 2. Threat model, trust boundaries, and assumptions

### 2.1 Assets

- protected repository refs and source history;
- branch/ruleset and required-check integrity;
- formal human review identity and decision history;
- GitHub, App, OIDC, model-provider, cloud, and deployment credentials;
- exact-head test, review, security, provenance, and operational evidence;
- product source, private repository content, business PII, and incident logs;
- runner, artifact, cache, package, and release integrity; and
- availability of shared review and merge queues.

### 2.2 Actors

| Actor | Assumed capability |
|---|---|
| External contributor | Controls fork/PR source, filenames, metadata, test output, and some comments |
| Compromised dependency/provider | Controls package/action/model/tool response or hosted artifact |
| Repository writer | Can push branches and influence PR content; cannot be assumed to have independent-review authority |
| Automated reviewer/bot | Can publish configured checks, statuses, comments, or formal bot reviews |
| Independent human reviewer | Can submit qualifying review under repository policy |
| Organization operator | Configures rulesets, secrets, Apps, runners, and required workflows |
| Concurrent automation writer | Can mutate a branch unless leases and expected-head checks prevent collision |

### 2.3 Trust boundaries

| Boundary | Less-trusted side | More-trusted side | Security invariant |
|---|---|---|---|
| PR head to trusted workflow | Fork/source tree, filenames, metadata, test behavior | Protected default-branch workflow and write credential | A privileged event never checks out or executes PR-controlled code; source is inert data or runs without privileged credentials. |
| Dispatch caller to central worker | Actor claims and payload fields | Protected `repository_dispatch` worker | Validate actor, repository, operation, PR, source head, live base, visibility, and replay identity against live GitHub state before privilege or model use. |
| Artifact/run to evidence consumer | Logs, archives, result markers, run metadata | Gate normalizer and scheduler | Bind repository, workflow source, run ID/attempt, artifact name/digest, schema, and exact revision; never trust a success-shaped payload alone. |
| Provider/model to review gate | Model text, tool output, provider status | Normalized finding/review evidence | Treat output as untrusted data, validate its schema and source receipt, and never promote it to human or merge authority. |
| Sandbox to public evidence | Child stdout/stderr, commands, exceptions, service logs | CI log, summary, comment, artifact, result JSON | Canonicalize and redact the complete boundary before truncation/serialization while preserving bounded ordinary diagnosis. |
| Scheduler to target repository | Proposed mutation and credential | Protected ref, review, status, or merge API | Require least privilege, branch-local ownership, current policy, exact expected head, and a last-moment live-state refresh. |
| Operator configuration to runtime | Rulesets, secrets, Apps, allowlists, workflow toggles | Organization fleet | Configuration is privileged change, not trusted merely because it exists; audit scope, issuer, review, and protected-main acceptance. |

### 2.4 Assumptions

- GitHub correctly authenticates API actors and preserves commit, review, check, and run identities, while configuration drift and compromised credentials remain in scope.
- Protected default-branch workflow source is trusted only after required current-head checks and qualifying review; a mutable branch name alone is not an immutable identity.
- Every API read is a time-bounded observation. A writer re-fetches live head, base, policy, and ownership state immediately before mutation.
- Credential values are provisioned outside source control, can be revoked, and are not legitimate diagnostic evidence. Availability of a credential does not expand its documented authority.
- Product source, PR prose, comments, logs, artifacts, package metadata, and provider/model responses can be malicious even when their transport is authenticated.
- Automated identities cannot become qualifying human reviewers through wording, token choice, or a success-shaped result.
- GitHub remains the durable evidence system of record subject to its configured retention; no separate evidence database is assumed.
- A fully compromised organization owner or GitHub control plane can override repository controls. The repository can reduce, detect, and reconstruct that risk but cannot cryptographically prevent the platform owner from exercising platform authority.

### 2.5 Input control

| Control class | Inputs | Required treatment |
|---|---|---|
| Attacker-controlled | PR/fork source, paths, refs, metadata, issue comments, child output, service logs, untrusted artifacts, source archives, model/tool text | Parse as data; bound size/time; canonicalize; validate schemas and identities; isolate execution; redact before publication. |
| Developer-controlled | Central workflow/script changes, prompts, action pins, lockfiles, tests, documentation | Treat as proposed code until protected review and exact-head gates pass; use immutable dependency identities and consumer canaries. |
| Operator-controlled | Rulesets, required workflows, Apps, OIDC audiences, secrets, allowlists, reruns, disables, rollback decisions | Require named authority, least privilege, change receipt, rollback, and post-change audit; never infer approval from operator access alone. |
| Platform/provider-controlled | GitHub API responses, OIDC claims, runner images, registries, model/provider responses | Authenticate transport and issuer, bind freshness and integrity, validate content, classify outages, and retain independent deterministic/human authorities. |

## 3. Attack surface, mitigations, and attacker stories

### 3.1 Entry points

PR events; dispatch payloads; workflow-call inputs; issue comments; scheduled sweeps; workflow artifacts; source archives; package registries; model responses; CLI arguments and environment allowlists; child stdout/stderr; service logs; GitHub API responses; review comments; status/check publication; and merge/fix APIs.

### 3.2 Threat and control matrix

| ID | STRIDE | Threat / realistic path | Primary controls | Residual risk / required evidence |
|---|---|---|---|---|
| TM-01 | Information disclosure | Child process prints token in stdout, timeout bytes, exception, service tail, command, or JSON result | Shared canonical redactor on every publication path; explicit sensitive values; no-output unsafe preflight | Unknown token formats and unbounded raw service files; adversarial regression and retention controls required |
| TM-02 | Elevation / disclosure | Broad `secrets: inherit` gives a reusable workflow unrelated credentials | Explicit secret contracts; job-level least privilege; migrate legacy deploy caller | Legacy caller remains inventory debt until replaced |
| TM-03 | Spoofing / elevation | Attacker sends a `repository_dispatch` payload naming another repo/head or replays a mention | Actor/repo allowlist, canonical payload hash, live PR comparison, exact-name replay ledger | Upstream identity-provider compromise; inspect issuer/audience and token issuance logs |
| TM-04 | Tampering | Stale check/review from predecessor head is reused after push | Exact commit/run binding, live refresh, last-push approval policy, expected-head mutation | GitHub policy configuration drift; audit rulesets continuously |
| TM-05 | Elevation | Automated model review is treated as qualifying independent human approval | Separate evidence classes; author/reviewer identity checks; GitHub aggregate review decision | Misconfigured ruleset or privileged token bypass; ruleset audit and negative merge tests |
| TM-06 | Elevation / tampering | `pull_request_target` checks out or executes malicious PR code with secrets/write token | Metadata-only bootstrap; privileged default-branch dispatch; low-privilege sandbox | Future workflow edit can reintroduce path; contract tests and CodeQL/Semgrep |
| TM-07 | Tampering / spoofing | Prompt injection makes reviewer call tools, reveal secrets, or emit success-shaped output | Treat source/comments as data; constrained tools/egress; structured output validation; source receipts | Model/tool vulnerabilities; independent deterministic gates and human review remain mandatory |
| TM-08 | Tampering | Compromised action/package/archive or mutable workflow ref changes executed code | Immutable pins, hashes/signatures, origin/redirect/member validation, trusted workflow SHA | Compromise of trusted publisher or signing root; provenance and rotation plan |
| TM-09 | Information disclosure | Anonymous/free provider receives private source or inherited provider keys | Trusted-base data-classification policy; provider-scoped environment; no credential on anonymous path | Incorrect classification; require accountable owner and negative private canary |
| TM-10 | Denial of service | Huge or adversarial log triggers quadratic redaction, memory growth, or service-file exhaustion | Linear parsing tests, timeouts, tail bounds after redaction | Total capture/file quotas are not fully solved by redaction; separate resource-limit work required |
| TM-11 | Tampering | Concurrent writer overwrites branch, resolves wrong thread, or merges moved head | Branch-local lease, last-moment refresh, expected-head API, no force-push | Actors outside lease protocol; GitHub protections and conflict detection |
| TM-12 | Repudiation | Merge or incident closure cannot be tied to exact evidence and operator | Run/attempt/revision receipts, formal review records, traceability, protected-main acceptance | Retention expiry; keep minimal durable receipt and hashes |
| TM-13 | Information disclosure | Per-item PII masking is removed and broad logs expose business content | Purpose-bound access, minimal evidence scope, short retention, audit, repository classification | Authorized-user misuse and mosaic inference; periodic access/retention review |
| TM-14 | Tampering | Retry converts integrity/auth/TLS/ref/schema failure into eventual green | Classified retry allowlist; permanent classes fail immediately | Misclassification; regression fixtures for every class and observable attempt ledger |
| TM-15 | Tampering / denial | Rollback restores vulnerable workflow or closes incident without consumer proof | Versioned rollback target, security review, reopen criteria, protected-main canary | Emergency rollback time pressure; require post-incident reconciliation |

### 3.3 Attack paths requiring explicit tests

#### 3.3.1 Credential evidence escape

1. A contributor causes a test or service to print a credential using JSON, ANSI/default-ignorable splits, multiline headers, nested shell commands, URL userinfo, or cross-stream fragments.
2. A wrapper captures or tails the text.
3. A partial redactor misses the form or redacts after tail selection.
4. The credential appears in a public log, summary, comment, artifact, or result marker.

Required counterevidence: complete-boundary redaction tests for completed, timeout, exception, command, service, and structured output; valid JSON and ordinary diagnostics preserved; fixed linear-time fixtures.

#### 3.3.2 Confused-deputy dispatch

1. A caller submits valid-looking repository, PR, head, base, and requested action fields.
2. A central worker trusts payload identity without live comparison.
3. The worker exchanges a privileged token and writes to the victim repository or branch.

Required counterevidence: actor and target allowlists; immutable default-branch worker; canonical schema; live repo/PR/head/base/ref comparison; exact invocation ledger; expected-head write.

#### 3.3.3 Reviewer spoofing

1. A bot publishes `APPROVED`, a success status, or approval-like prose.
2. Scheduler logic counts it as the required independent review.
3. A bypass-capable credential merges despite GitHub review state.

Required counterevidence: formal review source, exact commit, non-author/non-bot eligibility, aggregate GitHub review decision, ruleset, and negative merge-path fixtures.

### 3.4 Out-of-scope attacker stories

These stories do not become repository findings without an additional repository-controlled failure:

- compromise of GitHub's global control plane, an external provider's root signing authority, or a maintainer workstation with already-authorized organization-owner access;
- a fully authorized organization owner intentionally removing protections and audit history, although ruleset drift detection and external audit remain defense in depth;
- vulnerabilities in a product application's runtime that no central workflow executes, publishes, mutates, or supplies with authority;
- disclosure of intentionally public source to a provider explicitly approved for that public repository, absent credential, policy, or consent failure; and
- availability loss caused only by a declared external outage when the control plane fails closed and continues unrelated safe work.

Output-memory and service-file exhaustion are not out of scope, but they are explicitly unresolved by credential redaction alone and remain TM-10 work. Certification or regulatory compliance is also not inferred from this threat model.

## 4. Severity calibration

Severity depends on reachable authority, affected repositories, data classification, persistence, and whether GitHub protection or independent review still blocks impact.

| Severity | Repository-context examples |
|---|---|
| Critical | Attacker-controlled PR code executes with a write/secret-bearing trusted workflow; a confused deputy writes or merges a protected ref in another repository; a live organization credential is published with practical fleet-wide write authority. |
| High | Current-head required evidence can be forged into a false green; private source/PII is sent to an unauthorized provider; a compromised action or archive executes in a privileged job; a writer bypasses expected-head protection and corrupts a shared branch. |
| Medium | One repository's review/merge queue is persistently denied without a privilege or confidentiality breach; bounded sensitive business context is exposed only to an unintended but already authenticated audience; missing receipts prevent incident reconstruction while protected mutation remains blocked. |
| Low | Documentation, non-authorizing telemetry, or diagnostics drift without changing a trust boundary; a bounded optional provider failure has an accurate non-passing result and safe continuation path. |

A hypothetical injection without attacker control of the input, a stale record that is rejected before authorization, or a provider outage that remains visibly non-passing is not promoted merely because the vulnerability class could be severe elsewhere.

## 5. Privacy position

The system does not solve privacy by masking every name, email address, or business fact. That would erase the context required for investigation and review. Instead it limits who can access raw evidence, for what purpose, how long, and through which classified provider. Credential redaction remains mandatory because credentials are capability-bearing and never legitimate diagnostic content.

## 6. Residual risks and owners

| Risk | Owner | Closure evidence |
|---|---|---|
| Total stdout/stderr and service-log growth | Sandbox/output-limit owner | Bounded memory/file tests and protected-main hostile-output run |
| Legacy inherited deploy secrets | Deploy workflow owner | Explicit secret migration and real deployment canary |
| Reviewer availability | Organization governance owner | Eligible reviewer pool and counted exact-head approval receipt |
| Provider and GitHub outage | Platform operator | Queue-age telemetry, deferred work, and recovery run |
| Ruleset drift | Organization administrator | Scheduled ruleset audit and remediation receipt |
| Private-source model classification | Repository data owner | Trusted-base policy, negative control, provider-specific egress evidence |

Threats are reopened whenever source, identity, permissions, provider, retention, or deployment topology changes.

## 7. Exact source and test traceability

Paths below are the current concrete control and regression locations. A listed path is not proof that every branch is implemented; the closure and maturity columns name material gaps.

| Threat | Exact control source | Exact regression evidence | Closure boundary | Current maturity |
|---|---|---|---|---|
| TM-01 | `scripts/ci/redact_sensitive_log.py`; `scripts/ci/sandboxed_verify.py`; `scripts/ci/sandboxed_web_e2e.py` | `tests/test_sandboxed_verify.py`; `tests/test_sandboxed_web_e2e.py`; `tests/test_opencode_security_boundaries.py` | [PR #888](https://github.com/ContextualWisdomLab/.github/pull/888) and Draft [PR #906](https://github.com/ContextualWisdomLab/.github/pull/906) are closed unmerged as `superseded` incident evidence; current open integration and consumer proof are proposed by [PR #1031](https://github.com/ContextualWisdomLab/.github/pull/1031). Do not merge overlapping [PR #929](https://github.com/ContextualWisdomLab/.github/pull/929) in parallel. | `active_pr` |
| TM-02 | `.github/workflows/deploy-pages.yml`; `docs/automation/SECURITY.md` | `tests/test_automation_documentation_contract.py` | Documentation detects known debt; explicit workflow-call secret declarations and a runtime negative contract remain open. | `accepted_architecture` |
| TM-03 | `.github/workflows/agent-mention-router.yml`; `.github/workflows/opencode-review-dispatch.yml`; `scripts/ci/agent_mention_router.py`; `scripts/ci/agent_mention_sweep.py` | `tests/test_agent_mention_complete_payload_binding.py`; `tests/test_agent_mention_idempotency.py`; `tests/test_agent_mention_workflow_contract.py`; `tests/test_opencode_security_boundaries.py` | Named router/wrapper controls exist; end-to-end strict snapshot preservation remains proposed by Draft [PR #1021](https://github.com/ContextualWisdomLab/.github/pull/1021), the bounded successor to closed-unmerged [PR #840](https://github.com/ContextualWisdomLab/.github/pull/840). | `active_pr` |
| TM-04 | `scripts/ci/pr_head_replay_guard.py`; `scripts/ci/pr_review_merge_scheduler.py` | `tests/test_pr_head_replay_guard.py`; `tests/test_pr_review_merge_scheduler.py` | Enforcement still depends on current live ruleset configuration. | `implemented_on_protected_main` |
| TM-05 | `scripts/ci/pr_review_merge_scheduler.py`; `scripts/ci/opencode_existing_approval_gate.py`; `scripts/ci/noema_review_gate.py` | `tests/test_pr_review_merge_scheduler.py`; `tests/test_opencode_existing_approval_gate.py`; `tests/test_noema_review_gate.py` | The software enforces eligibility; human reviewer capacity remains external governance work. | `implemented_on_protected_main` |
| TM-06 | `.github/workflows/opencode-review.yml`; `.github/workflows/opencode-review-dispatch.yml`; `.github/workflows/security-scan.yml` | `tests/test_opencode_security_boundaries.py`; `tests/test_review_execution_contracts.py`; `tests/test_required_workflow_queue_contract.py` | Covered entrypoints are protected; every new entrypoint must join the inventory. | `implemented_on_protected_main` |
| TM-07 | `scripts/ci/opencode_review_normalize_output.py`; `scripts/ci/opencode_adversarial_receipts.py`; `scripts/ci/review_execution_contracts.py` | `tests/test_opencode_review_normalize_output.py`; `tests/test_opencode_adversarial_receipts.py`; `tests/test_review_execution_contracts.py` | Defense in depth does not replace deterministic and qualifying-human gates. | `implemented_on_protected_main` |
| TM-08 | `scripts/ci/compile_opencode_review_lock.sh`; `scripts/ci/materialize_base_python_requirements.py`; `.github/workflows/trusted-uv-materializer-quality-ci.yml` | `tests/test_trusted_uv_download_contract.py`; `tests/test_uv_redirect_boundary.py`; `tests/test_strix_workflow_dependency_hashes.py` | Covered toolchains are pinned; new ecosystems require an inventory extension. | `implemented_on_protected_main` |
| TM-09 | `.github/workflows/opencode-review-dispatch.yml`; `.github/workflows/noema-review.yml`; `.github/workflows/strix.yml` | `tests/test_opencode_agent_contract.py`; `tests/test_noema_review_gate.py`; `tests/test_opencode_security_boundaries.py` | Routing is tested; repository data-owner consent/classification remains governance evidence. | `accepted_architecture` |
| TM-10 | `scripts/ci/redact_sensitive_log.py`; `scripts/ci/sandboxed_verify.py`; `scripts/ci/sandboxed_web_e2e.py` | `tests/test_sandboxed_verify.py`; `tests/test_sandboxed_web_e2e.py`; `tests/test_opencode_security_boundaries.py` | Redaction is active work; total capture and service-file quotas remain separate planned work. | `active_pr` |
| TM-11 | `scripts/ci/pr_review_merge_scheduler.py`; `scripts/ci/pr_review_fix_scheduler.py`; `scripts/ci/pr_auto_rebase.py` | `tests/test_pr_review_merge_scheduler.py`; `tests/test_pr_review_fix_scheduler.py`; `tests/test_pr_auto_rebase.py` | Expected-head guards exist; a shared cross-workflow lease is planned in issue #890. | `planned` |
| TM-12 | `scripts/ci/opencode_dispatch_status.py`; `scripts/ci/agent_mention_router.py`; `scripts/ci/pr_review_merge_scheduler.py` | `tests/test_agent_mention_receipt_authority.py`; `tests/test_agent_mention_artifact_ledger.py`; `tests/test_pr_head_replay_guard.py` | Receipts are distributed and retention can expire them; recoverable mention claims are planned. | `accepted_architecture` |
| TM-13 | `docs/automation/SECURITY.md`; `.github/workflows/opencode-review-dispatch.yml`; `.github/workflows/noema-review.yml` | `tests/test_opencode_agent_contract.py`; `tests/test_automation_documentation_contract.py` | Public/private routing is checked; no complete access/retention audit gate exists. | `accepted_architecture` |
| TM-14 | `scripts/ci/run_opencode_review_model_pool.sh`; `scripts/ci/pr_review_merge_scheduler.py`; `scripts/ci/strix_model_utils.sh` | `tests/test_opencode_model_pool_runner.py`; `tests/test_pr_review_merge_scheduler.py`; `tests/test_strix_nvidia_nim_not_found_fallback.py` | Covered retry loops are classified; new paths require equivalent fixtures. | `implemented_on_protected_main` |
| TM-15 | `docs/automation/RUNBOOK.md`; `docs/automation/INCIDENT_RUNBOOK.md`; `scripts/ci/pr_review_merge_scheduler.py` | `tests/test_pr_review_merge_scheduler.py`; `tests/test_automation_documentation_contract.py` | Guarded merge tests exist; fleet rollback rehearsal and consumer receipts remain operational evidence. | `accepted_architecture` |

Cross-document requirement status remains in [TRACEABILITY.md](TRACEABILITY.md). Incident commands and evidence templates are in [RUNBOOK.md](RUNBOOK.md).
