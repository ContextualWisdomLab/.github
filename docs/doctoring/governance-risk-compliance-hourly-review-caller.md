# Governance Risk Compliance Hourly Review Caller

## Decision

`ContextualWisdomLab/.github` owns the hourly review-repair scheduler and its privileged OpenCode worker. The GRC product receives a small caller at minute 43 of every hour. Each heartbeat inspects up to 50 open pull requests, dispatches at most one repair, and preserves an in-flight writer. The caller targets the product's protected `develop` branch.

The scheduler requires root-cause analysis and remediation feasibility before a branch mutation. A two-hour same-head retry floor accommodates central OpenCode, Noema, Strix, security, and coverage work without treating provider or runner latency as a source defect or dispatching duplicate writers.

## Product ownership boundary

`ContextualWisdomLab/governance-risk-compliance` owns policy, control, risk, evidence, and compliance-audit truth. It does not absorb central CI/security implementation or another CWL product's authority.

- Keyverse owns identity and federation. A repair must not invent authentication inside the GRC product or weaken its local-only preview boundary.
- GRC retains exact operational evidence values. Repair must not introduce blanket or destructive PII masking; it must preserve authenticated purpose and tenant authorization, encryption, audit, retention, and purpose-specific omission of unrelated fields.
- Orgmetra, accounting, billing, naruon, enterprise architecture, and semantic data products remain contract consumers or evidence producers within their own ownership boundaries.
- Product repair may change the validated same-repository PR branch only. Central workflows, credentials, rulesets, and provider configuration remain owned by `.github`.

## Credential and model boundary

The caller keeps the workflow-generated token read-only and forwards only the established scheduler mutation credentials. It contains no model-provider secret.

The central worker may use `NVIDIA_NIM_API_KEY` through its reviewed credential boundary. The caller and GRC repository must not use `COPILOT_GITHUB_TOKEN`. The independent read-only reviewer keeps its separate credential and model-pool contract; review and write-capable repair remain distinct controls.

The scheduler dispatches at most one repair per heartbeat. A repair worker cannot approve its own change, reinterpret failed or queued checks as success, lower protection, merge, publish, or release.

## Exact-head merge contract

A GRC pull request may merge only after the unchanged current head has:

1. terminal-success product, coverage, SAST, security, and supply-chain checks;
2. zero valid unresolved review findings;
3. a current-head semantic review verdict;
4. independent non-author approval when required by live protection;
5. a compatible live base and ordinary expected-head merge authority; and
6. current documentation, CHANGELOG, ADR, and APA 7th references for standards-backed decisions.

Queued, pending, skipped-required, cancelled, stale, predecessor-head, local-only, author-only, synthetic, or model-only evidence is not acceptance. Review or check latency is not a blocker to examining the next eligible PR or buyer-visible product gap, but it is never permission to bypass a gate.

## Activation and fail-closed behavior

GitHub scheduled workflows run from the default branch. The heartbeat becomes active only after this caller reaches protected `.github` `main`. The central scheduler also requires `ContextualWisdomLab/governance-risk-compliance` in the organization target allowlist. A missing target or mutation authority fails closed.

The caller does not create a second provider configuration, review agent, or merge engine. Rollback removes the caller, focused contract, quality-workflow path tracking, and this doctoring record together; it does not weaken the reusable central scheduler.

## References

GitHub, Inc. (n.d.-a). *Events that trigger workflows*. GitHub Docs. Retrieved August 18, 2026, from https://docs.github.com/actions/using-workflows/events-that-trigger-workflows

GitHub, Inc. (n.d.-b). *Reusing workflow configurations*. GitHub Docs. Retrieved August 18, 2026, from https://docs.github.com/actions/using-workflows/reusing-workflows

National Institute of Standards and Technology. (2024). *The NIST Cybersecurity Framework (CSF) 2.0* (NIST CSWP 29). U.S. Department of Commerce. https://doi.org/10.6028/NIST.CSWP.29
