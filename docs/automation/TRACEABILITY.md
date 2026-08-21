# Requirements and evidence traceability

Status: living authoritative matrix
Last reviewed: 2026-08-16

Canonical maturity states are defined in [DOCUMENTATION_AUDIT.md](DOCUMENTATION_AUDIT.md): `implemented_on_protected_main`, `active_pr`, `accepted_architecture`, `planned`, `research_only`, `superseded`, and `out_of_scope`. Every maturity cell contains exactly one canonical state; explanatory qualifiers belong in the evidence or closure columns. A row marked `implemented_on_protected_main` still requires fresh exact-head evidence for each later change; a row marked `active_pr` is never shipped truth.

## 1. Product and technical requirements

Receipt names describe the required evidence shape; they are not claims that a particular transient run is current. A mutation must re-fetch the live receipt.
Repository locators below are literal paths with no globs. External canaries and live API receipts are explicitly labeled rather than misrepresented as repository files.

| Requirement | TRD / ADR | Implementation/source locator | Test/evidence locator | Required gate / receipt authority | Owner / closure target | Maturity |
|---|---|---|---|---|---|---|
| `PRD-01` fresh live state | `TRD-EVT-01`, ADR-0007 | `scripts/ci/pr_review_merge_scheduler.py`; `scripts/ci/agent_mention_sweep.py` | `tests/test_pr_review_merge_scheduler.py`; `tests/test_agent_mention_sweep.py` | `scan-pr-queue` plus live PR/ruleset API snapshot | automation maintainer / every decision | `implemented_on_protected_main` |
| `PRD-02` exact head + live base | `TRD-REV-01`, ADR-0002/0014 | `scripts/ci/pr_head_replay_guard.py`; `.github/workflows/opencode-review-dispatch.yml`; `.github/workflows/pr-review-autofix.yml` | `tests/test_pr_head_replay_guard.py`; `tests/test_opencode_review_context.py`; `tests/test_pr_review_fix_scheduler.py` | exact-head Check Runs plus independently resolved current base and expected-head mutation response | workflow owners / before every write | `accepted_architecture` |
| `PRD-03` authority separation | `TRD-AUTH-01`, ADR-0005/0015/0016 | `scripts/ci/opencode_review_normalize_output.py`; `scripts/ci/pr_review_merge_scheduler.py` | `tests/test_opencode_review_normalize_output.py`; `tests/test_pr_review_merge_scheduler.py` | distinct Check/Status/Review/thread/ruleset objects plus scheduler v2 receipt | governance maintainer / every merge | `implemented_on_protected_main` |
| `PRD-04` independent approval | `TRD-AUTH-01`, ADR-0005/0016 | `scripts/ci/audit_central_required_workflows.py`; `scripts/ci/pr_review_merge_scheduler.py` | `tests/test_central_required_workflow_ruleset_audit.py`; `tests/test_scheduler_independent_approval_gate.py` | live review decision, qualifying non-author formal review and ruleset | repository admins / before merge | `active_pr` |
| `PRD-05` writer lease | `TRD-WRITE-01`, ADR-0001 | `scripts/ci/pr_review_merge_scheduler.py`; `.github/workflows/pr-review-autofix.yml`; `docs/automation/CONTINUATION_RUNBOOK.md` | `tests/test_pr_review_merge_scheduler.py`; `tests/test_pr_review_fix_scheduler.py` | live branch/head observation plus expected-head GitHub response | active branch writer / immediately before mutation | `accepted_architecture` |
| `PRD-06` work conservation | `TRD-RUN-01`, ADR-0007 | `.github/workflows/pr-review-merge-scheduler.yml`; `AGENTS.md`; `docs/automation/CONTINUATION_RUNBOOK.md`; `docs/automation/UML.md` | `tests/test_required_workflow_queue_contract.py`; `tests/test_automation_documentation_contract.py`; `tests/test_automation_historical_loop_supersession_contract.py`; external continuation receipt | queue sweep plus `USER_REDIRECTION_INCIDENT` same invocation recovery; when two safe lanes exist at least two materially distinct actions with a non-documentation action when available; otherwise two fresh whole-queue sweeps before exit | automation operator / after every meta action and before run exit | `accepted_architecture` |
| `PRD-07` RCA + feasible remedy | `TRD-RETRY-01`, ADR-0003 | `ci-review-prompt.md`; `code-reviewer-prompt.md`; `docs/automation/RUNBOOK.md` | `tests/test_adversarial_evidence.py`; `tests/test_opencode_adversarial_receipts.py`; `tests/test_automation_documentation_contract.py` | source-backed finding/RCA, `remediation_candidate` evidence, exact-head repair and protected recovery receipt | incident owner / before closure | `accepted_architecture` |
| `PRD-08` safe diagnostic redaction | `TRD-LOG-01`, ADR-0009 | `scripts/ci/redact_sensitive_log.py`; `scripts/ci/sandboxed_verify.py`; `scripts/ci/sandboxed_web_e2e.py` | `tests/test_opencode_security_boundaries.py`; `tests/test_sandboxed_verify.py`; `tests/test_sandboxed_web_e2e.py` | exact-head redaction checks, then protected-main/consumer result markers | sandbox owners / current open successor #1031 + protected consumer canary | `active_pr` |
| `PRD-09` documentation graph | `TRD-IF-01`, ADR-0007/0008 | `docs/automation/DOCUMENTATION_AUDIT.md`; `docs/automation/README.md`; `docs/automation/EVENT_CONTRACTS.md`; `ARCHITECTURE.md` | `tests/test_automation_documentation_contract.py`; `tests/test_pr_governance_audit_contract.py`; `tests/test_automation_historical_loop_supersession_contract.py` | documentation contract, link/diagram/standards audit, `git diff --check`, reviewer approval | architecture maintainers / current canonical documentation PR | `active_pr` |
| `PRD-10` protected-main acceptance | `TRD-REV-01`, ADR-0006 | `.github/workflows/opencode-review.yml`; `.github/workflows/pr-review-merge-scheduler.yml`; `docs/automation/RUNBOOK.md` | `tests/test_required_workflow_queue_contract.py`; `tests/test_pr_review_merge_scheduler.py`; real-consumer canary receipt | protected commit, workflow source, scenario, negative control, rollback receipt | service owner / after protected integration | `accepted_architecture` |
| `PRD-11` thin modular consumers | `TRD-IF-01`, ADR-0008/0012/0014 | `.github/workflows/opencode-review.yml`; `.github/workflows/noema-review.yml`; `.github/workflows/strix.yml`; `.github/workflows/pr-review-fix-scheduler.yml`; `.github/workflows/deploy-pages.yml` | `tests/test_required_workflow_queue_contract.py`; `tests/test_central_required_workflow_ruleset_audit.py`; `tests/test_automation_documentation_contract.py` | ruleset source/ref plus positive/negative consumer run | interface owners / before breaking change | `accepted_architecture` |
| `PRD-12` model credential policy | `TRD-SEC-01`, ADR-0004/0011 | `.github/workflows/opencode-review-dispatch.yml`; `.github/workflows/noema-review.yml`; `.github/workflows/strix.yml` | `tests/test_opencode_security_boundaries.py`; `tests/test_opencode_model_pool_runner.py`; `tests/test_strix_nvidia_nim_not_found_fallback.py` | per-job secret map, provider result, redacted log, deterministic gates | security/workflow owners / every provider path change | `implemented_on_protected_main` |
| `PRD-13` PII alternative controls | `TRD-SEC-01`, `TRD-RET-01` | `docs/automation/SECURITY.md`; `.github/workflows/opencode-review-dispatch.yml`; `.github/workflows/noema-review.yml` | `tests/test_opencode_agent_contract.py`; `tests/test_automation_documentation_contract.py`; service privacy/access review | purpose/audience/retention/deletion/access receipt | data/service owner / before processing business PII | `accepted_architecture` |
| `PRD-14` quality/readability | verification §12, ADR-0012 | `pyproject.toml`; `requirements-opencode-review-ci.txt`; `requirements-opencode-review-ci-hashes.txt`; `.github/workflows/trusted-uv-materializer-quality-ci.yml` | `tests/test_repository_branch_coverage_execution_sandboxes.py`; `tests/test_trusted_uv_materializer_quality_workflow_contract.py`; compile/coverage/interrogate receipts | exact-head tests, 100% owned production statement/branch and public docstrings | change author / before PR readiness | `implemented_on_protected_main` |

## 2. Documentation coverage

| Artifact | Required content | Machine gate | Status |
|---|---|---|---|
| PRD | users, two modes, outcomes, degraded behavior, acceptance/non-goals | file/index/term contract | `active_pr` |
| TRD | events, revisions, evidence authority, permissions, retries, leases, redaction | file/index/source-name contract | `active_pr` |
| Architecture | contexts, components, planes, trust/failure boundaries | Mermaid and source-name contract | `active_pr` |
| Data model / ERD | conceptual vs persisted and evidence/governance/remediation/continuation/documentation entities | entity/naming/cardinality/link contract | `active_pr` |
| UML | component, two sequences, state, authority, topology, retry, sandbox, lease/continuation, documentation→source handoff, and `USER_REDIRECTION_INCIDENT` same invocation recovery | diagram-section/fence + historical-loop contract | `active_pr` |
| Security / threat model | required attack paths, privacy alternative, residual risk | term/link contract | `active_pr` |
| Test strategy | realistic gate, security, performance, consumer proof, documentation fitness | term/link/standards contract | `active_pr` |
| Operability / runbook | SLI/SLO, queue/provider failures, exact queries, rollback, retention, receipt, closure/reopen, same-invocation premature-stop recovery | term/link + historical-loop contract | `active_pr` |
| Whole-conversation audit | maturity states, central/leaf ownership, no-soft-timeout, user-redirection recovery, fitness findings | indexed file + documentation contract | `active_pr` |
| ADR set | sixteen indexed decisions with alternatives, tests, rollback, supersession | index/file/section contract | `active_pr` |
| Standards doctoring | final/draft version discipline and APA 7 references | standards-freshness contract | `active_pr` |

## 3. Redaction incident lineage

- `ContextualWisdomLab/.github#841` is closed/unmerged historical origin evidence. It established the disclosure concern but mixed unrelated scope; it is `superseded` as an integration path.
- `ContextualWisdomLab/.github#842` is closed/unmerged historical RED→GREEN and exhaustive-boundary evidence. Its final blobs removed current-source defects but its reachable PR history retained secret-shaped test fixtures that kept Secret Scan red; it is `superseded` as an integration path.
- `ContextualWisdomLab/.github#888` is closed/unmerged `superseded` incident evidence. It initially replayed the final ten #842 blobs without predecessor fixture history, but a later committed credential-shaped fixture made its reachable range fail Secret Scan again.
- `ContextualWisdomLab/.github#906` is closed/unmerged `superseded`. It was a Draft clean-history successor and is no longer an open integration path.
- `ContextualWisdomLab/.github#929` is an overlapping open predecessor for atomic JSON layout. Do not merge it in parallel with its successor.
- `ContextualWisdomLab/.github#1031` is the current open `active_pr` successor. It carries the sandbox redaction repair, wrapper/command redaction evidence, and the Actions group-marker JSON layout fix for [Issue #908](https://github.com/ContextualWisdomLab/.github/issues/908). Bounded wrapper recursion remains [Issue #907](https://github.com/ContextualWisdomLab/.github/issues/907). Its exact-head checks, reviews, and threads must be re-fetched at every decision; predecessor or queued evidence is non-authorizing.
- Output-memory and service-file quotas remain a separate `planned` resource-safety requirement. Redaction completion must not be reported as resource-exhaustion closure.
- Every #1031 head change invalidates predecessor test counts, coverage counts, reviews, and run IDs. Protected-main/consumer synthetic credential canaries are required before operational closure.

## 4. Whole-conversation and documentation governance traceability

| Decision / evidence source | Canonical artifact | Maturity | Rule |
|---|---|---|---|
| Repeated instruction to continue after merge/review/check/doc work | ADR-0007; `CONTINUATION_RUNBOOK.md`; `UML.md`; `DOCUMENTATION_AUDIT.md` | `active_pr` | Meta/control actions and one substantive result are intermediate while a safe lane remains; hourly recurrence is not a soft timeout. A user-reported premature stop is `USER_REDIRECTION_INCIDENT`: recovery occurs in the same invocation, includes a non-documentation lane when available, and ends only after the required work plus two fresh whole-queue sweeps or genuine tool/runtime exhaustion. |
| Conversation/planning packs across TEPP, OriginWeave, EmbedRelay, MHTML ETL, LifeOS and leaf products | `DOCUMENTATION_AUDIT.md`; central/leaf Architecture | `active_pr` | Revalidate shared automation decisions; leaf product semantics remain `out_of_scope` here and are not copied into central architecture. |
| ADR/PRD/TRD/UML/ERD completeness request | documentation graph + this traceability matrix | `active_pr` | A prose assessment alone is insufficient; gaps become canonical GitHub mutations and machine contracts, and documentation repair returns to non-documentation execution whenever a safe lane exists. |
| Architecture/requirements/product-quality standards | `docs/doctoring/automation-control-plane-standards.md` | `active_pr` | Final publications are normative baselines; drafts are informative only. |
| Logical evidence-store relationships | `DATA_MODEL.md`; `ERD.md` | `active_pr` | Conceptual model only; material persistence requires a separate ADR and privacy/tenancy/DR design. |

## 5. Known gaps and next evidence

| Gap | Risk | Next bounded evidence | Maturity |
|---|---|---|---|
| No persisted cross-repository continuation/writer ledger | collision and queue-starvation reconstruction | decide whether GitHub Project/artifact state is sufficient before proposing persistence | `planned` |
| SLI aggregation incomplete | buyer cannot quantify reliability | [PR #905](https://github.com/ContextualWisdomLab/.github/pull/905) implements the read-only finite-cardinality `control_plane_sli_receipt`; require exact-head 100% statement/branch/docstring gates, current review, protected integration, and real receipt canaries before claiming operational coverage | `active_pr` |
| Sandbox total-output/service-file quota incomplete | memory/disk DoS | fail-first hostile-output quota tests and separate implementation PR | `planned` |
| Legacy `deploy-pages.yml` secret/input trust boundary | excess secret exposure and unsafe reusable inputs | [PR #901](https://github.com/ContextualWisdomLab/.github/pull/901) explicit two-secret interface plus bounded `project_name`/`build_dir`/`custom_domain` validation and real deployment positive/negative canary | `active_pr` |
| Undeclared scheduler/rebase reusable secrets | caller ambiguity and excess exposure | declare and map secrets in the three exact workflows registered by `SECURITY.md`; add negative caller tests and consumer receipts | `planned` |
| Operational receipts distributed | incident closure hard to audit even with a local SLI receipt | integrate accepted #905 receipt with dated protected-main/consumer acceptance evidence without inventing a new persistence authority | `planned` |
| Project #1 requires GraphQL/`gh` project scope | agents without that capability cannot acquire visible project item | add supported connector or ensure native PR auto-add; never invent state | `planned` |
| Master context current-state section is dated | stale operational narrative | separate timeless context from generated/daily live-state appendix | `planned` |
| Explicit dispatch/result schema versions not universal | compatibility ambiguity | version all central dispatch/result contracts with migration/negative tests | `planned` |

## 6. Audited implementation-gap lineage

An issue records planned work; it does not implement the work it describes. An open PR moves a gap to `active_pr` only for that exact change line; it is not protected-main implementation.

| Gap | Live object | Current boundary and required closure | Maturity |
|---|---|---|---|
| `IG-001` dispatch snapshot preservation | [PR #1021](https://github.com/ContextualWisdomLab/.github/pull/1021) | Draft [PR #1021](https://github.com/ContextualWisdomLab/.github/pull/1021) is the bounded successor to closed-unmerged [PR #840](https://github.com/ContextualWisdomLab/.github/pull/840). It proposes an end-to-end versioned envelope, live-base binding, and review-only route; protected-main consumer acceptance remains required. | `active_pr` |
| `IG-002` counted independent reviewer | [Issue #772](https://github.com/ContextualWisdomLab/.github/issues/772) | Tracks planned implementation of a non-author human reviewer path that GitHub counts. | `planned` |
| `IG-003` external-head convergence | [Issue #889](https://github.com/ContextualWisdomLab/.github/issues/889) | Tracks planned implementation of one safe review-or-reject contract across privileged entrypoints. | `planned` |
| `IG-004` cross-workflow writer fencing | [Issue #890](https://github.com/ContextualWisdomLab/.github/issues/890) | Tracks planned implementation of a shared repository/branch lease, TTL, heartbeat, takeover, and fencing. | `planned` |
| `IG-005` authoritative Strix result | [Issue #891](https://github.com/ContextualWisdomLab/.github/issues/891) | Tracks planned implementation of a fail-closed terminal gate when authoritative scan evidence is absent. | `planned` |
| `IG-006` merge mode and mutation authority | [Issue #892](https://github.com/ContextualWisdomLab/.github/issues/892) | Tracks planned implementation of one executable credential/mode authority table. | `planned` |
| `IG-007` recoverable mention claim | [Issue #893](https://github.com/ContextualWisdomLab/.github/issues/893) | Tracks planned recoverable claim states and fencing without weakening completed-request idempotency. | `planned` |
| `IG-008` truthful scheduler terminal result | [PR #899](https://github.com/ContextualWisdomLab/.github/pull/899) | The active repair returns a non-zero process result only after the bounded scan and structured summary when a material decision is `action_error`; exact-head checks/review and protected integration remain required. | `active_pr` |

## 7. Standards traceability

Research status, normative version choices, applied implications, and APA 7 references are maintained in [`../doctoring/automation-control-plane-standards.md`](../doctoring/automation-control-plane-standards.md). The current baseline explicitly distinguishes:

- SLSA 1.2 as the current SLSA specification;
- NIST SP 800-218 SSDF 1.1 as current final versus the SSDF 1.2 / SP 800-218 Rev. 1 initial public draft as informative;
- ISO/IEC/IEEE 42010:2022 for architecture description;
- ISO/IEC/IEEE 29148:2018 as current published requirements engineering versus Edition 3 DIS as informative until publication;
- ISO/IEC 25010:2023 for product quality; and
- the named final testing/security/AI/observability/assurance sources in the doctoring record.

No citation alone establishes certification, formal conformance, a SLSA level, SOC 2, CSAP, or operating effectiveness.