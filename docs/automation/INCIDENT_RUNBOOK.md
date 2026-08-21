# Incident runbook — automation control plane

Status: accepted baseline
Last reviewed: 2026-08-09

Use this document for severity, RCA, repair, and closure decisions. The executable read-only diagnostics, guarded rerun/disable/rollback templates, ownership placeholders, evidence-deletion safeguards, and canary receipt are in [RUNBOOK.md](RUNBOOK.md).

## 1. Use this runbook for

False-green or stale gates; unauthorized or raced writes; secret/log disclosure; privileged untrusted-code execution; scanner/reviewer failure; queue starvation; artifact/provenance mismatch; ruleset drift; broken central consumers; and documentation that materially misstates an authority or recovery boundary.

## 2. Severity

| Severity | Examples | Initial response objective |
|---|---|---|
| SEV-1 | credential exposure, unauthorized protected write/merge, privileged execution of malicious PR code | contain immediately; rotate/revoke affected authority; preserve minimal evidence |
| SEV-2 | false-green required gate, organization-wide consumer breakage, widespread queue starvation | stop affected mutation path; establish scope and safe fallback |
| SEV-3 | one PR/provider/toolchain blocked with other safe paths available | classify, repair or defer, continue queue |
| SEV-4 | documentation/telemetry drift without current unsafe behavior | record and repair in bounded docs/control increment |

## 3. First response

1. Record repository, PR, exact head, live base tip, workflow source SHA, run ID/attempt, event, actor, and first observed time.
2. Stop only the affected mutation/credential path. Do not disable unrelated security gates or the whole fleet without evidence.
3. For suspected credential disclosure, restrict the evidence, revoke/rotate the capability, and preserve only bounded redacted receipts.
4. Re-fetch live state; do not trust screenshots, remembered SHAs, or predecessor-run summaries.
5. Identify the first failing boundary and classify the affected authority: source, workflow, credential, check, status, review, merge, artifact, or operations.
6. Move unrelated executable work to another branch/repository/lane.

## 4. RCA and feasibility

State separately:

- symptom;
- immediate cause;
- root-cause hypothesis and evidence that could falsify it;
- owner boundary;
- affected and unaffected paths;
- materially distinct remedies;
- feasibility of each remedy under current permissions, policy, writer state, dependencies, rollback, and acceptance test; and
- smallest root-cause-changing repair.

Do not label `failed`, `pending`, `cancelled`, `rate_limited`, or `action_required` as a root cause. Do not propose a credential, reviewer, bypass, or branch rewrite that does not exist or cannot be safely verified.

## 5. Repair and recovery

1. Add a fail-first regression at the closest durable contract.
2. Apply the smallest cohesive production repair on a branch with a clear writer lease.
3. Run the original reproduction, focused suite, full suite, coverage/docstrings, security/supply-chain gates, and documentation checks.
4. Push without rewriting shared history; bind every hosted result to the new head.
5. Obtain current-head automated and qualifying independent review; resolve only addressed threads.
6. Merge through protection and expected-head semantics.
7. Execute protected-main central acceptance and an affected real-consumer positive/negative scenario where applicable.
8. Update traceability, ADR, operations, and change history.

## 6. Playbooks

### 6.1 Suspected credential disclosure

- Restrict or delete public evidence only through supported GitHub controls; do not copy the secret into comments or tickets.
- Rotate/revoke first when the value may be live.
- Determine every publication path: stdout, stderr, timeout, exception, service file/tail, command, result JSON, summary, comment, artifact, cache.
- Test the exact encoding/evasion form and neighboring non-sensitive diagnostics.
- Redact complete content before truncation and validate that no stream/result concatenation reconstructs the value.
- Close only after protected-main/consumer output proves redaction and ordinary diagnosis remains intact.

### 6.2 Stale or false-green evidence

- Capture the claimed and actual source/workflow/base/run identities.
- Mark mismatched evidence non-authorizing; do not rerun before understanding the binding defect.
- Repair the producer/consumer identity contract and add moved-head/live-base/synthetic-merge negative tests.
- Re-run all evidence on the new exact head; predecessor approvals do not transfer.

### 6.3 Queue starvation or provider outage

- Read queue age and provider failure once; deduplicate dispatches by PR/head/run identity.
- Defer the affected action and work another ledger lane.
- Retry only documented transient classes within a budget.
- Escalate capacity/permission only when it is the sole remaining fleet prerequisite.

### 6.4 Concurrent writer or moved branch

- Stop source writes immediately.
- Fetch exact remote head/base and compare trees/lineage; preserve both writers' work.
- Move to a disjoint task or prepare a non-destructive reconciliation.
- Never force-push, select `ours/theirs` wholesale, or manufacture a repair workflow.

### 6.5 Ruleset or reviewer-governance drift

- Fetch live ruleset/branch protection, required contexts, review count, last-push dismissal, CODEOWNERS, and bypass actors.
- Keep automation checks and formal human approval separate.
- Restore policy through an independently reviewed administrative change; do not compensate in source with fake approval.

## 7. Rollback

Rollback selects a reviewed known-good version and names the security trade-off. If the previous version contains the incident cause, disable the affected optional path or introduce a narrow fail-closed guard instead of restoring it. Re-run exact protected-main and consumer acceptance after rollback.

## 8. Closure and reopening

An incident closes only when:

- the root cause and affected scope are evidence-backed;
- the durable regression fails before and passes after the repair;
- the integrated protected commit is identified;
- required exact-head gates and qualifying review passed without bypass;
- protected-main or real-consumer positive/negative scenarios passed;
- rollback and monitoring are documented; and
- traceability and authoritative docs are current.

Reopen on any contradictory protected-main/consumer result, recurrence, newly discovered publication path, ruleset drift, or evidence that the accepted revision was not the one executed.
