# Traceability: requirements, decisions, implementation, and evidence

Status: authoritative map; implementation state is relative to protected main
`6eb06cdd08c79a06f7b390069d4ffa49e2eb7dba` observed on 2026-08-09.

## Requirement-to-evidence matrix

| Requirement | Governing decision | Implementation/evidence surface | Verification and state |
|---|---|---|---|
| PRD-001 exact source/live-base binding | [ADR-0002](adr/0002-exact-head-and-live-base-binding.md) | `scripts/ci/pr_review_merge_scheduler.py`, `scripts/ci/pr_head_replay_guard.py` | scheduler/replay-guard tests; dispatch-envelope hardening pending in `ContextualWisdomLab/.github#840` |
| PRD-002 central control plane/thin leaf | [ADR-0008](adr/0008-central-control-plane-thin-leaf-contract.md) | required/reusable workflows and `.github/workflows/audit-central-ruleset.yml` | workflow-contract and ruleset-audit tests; implemented with documented migration edges |
| PRD-003 evidence/authority separation | [ADR-0005](adr/0005-independent-review-governance.md) | review gates, scheduler classifiers, GitHub rulesets | scheduler/review-gate tests; formal independent approval still externally supplied |
| PRD-004 fail closed | [ADR-0002](adr/0002-exact-head-and-live-base-binding.md), [ADR-0004](adr/0004-minimal-reusable-workflow-secrets.md) | validation/materialization/review helpers | adversarial, workflow, security-boundary, and integrity tests |
| PRD-005 bounded classified retry | [ADR-0003](adr/0003-classified-bounded-retries.md) | provider runners, GitHub API callers, dispatch/status helpers | timeout, provider exhaustion, permanent-failure, and retry-budget tests; terminal scheduler failure propagation tracked by `ContextualWisdomLab/.github#894` |
| PRD-006 one writer/read-only audit | [ADR-0001](adr/0001-writer-lease-and-read-only-fleet-auditor.md) | workflow concurrency, scheduler guards, fleet audit | concurrency and audit contract tests; lease is currently distributed across GitHub concurrency/live-head checks |
| PRD-007 eligible independent review | [ADR-0005](adr/0005-independent-review-governance.md) | formal GitHub reviews and protected rulesets | current-head reviewer eligibility; organization remediation tracked by `ContextualWisdomLab/.github#772` |
| PRD-008 work conservation | [ADR-0007](adr/0007-work-conserving-automation.md) | hourly automation prompt and queue/handoff contract | prompt updated 2026-08-09; repository persistence is policy/docs rather than a dedicated queue service |
| PRD-009 protected-main closure | [ADR-0006](adr/0006-protected-main-operational-closure.md) | real consumer workflow run and handoff record | required for incident closure; evidence is per change |
| PRD-010 minimal secrets | [ADR-0004](adr/0004-minimal-reusable-workflow-secrets.md) | explicit job permissions, App/OIDC/token selection | security-boundary/workflow tests; remaining `secrets: inherit` guidance is a migration gap |
| PRD-011 safe diagnostics | [ADR-0003](adr/0003-classified-bounded-retries.md), [SECURITY.md](SECURITY.md) | sandbox/sanitization/redaction helpers | sanitization/sandbox tests; subprocess-log hardening pending in `ContextualWisdomLab/.github#842` |
| PRD-012 complete realistic tests | [TEST_STRATEGY.md](TEST_STRATEGY.md) | `tests/`, coverage/docstring gates, sandbox helpers | changed behavior requires 100% owned statement/branch coverage plus security/concurrency/consumer cases |
| PRD-013 code-current docs | this documentation spine | `docs/automation/` and entry-point links | `tests/test_automation_documentation_contract.py` |

## Threat-to-control trace

| Threat | Preventive/detective contract | Required verification family |
|---|---|---|
| TM-001 actor/repository spoofing | [SECURITY.md](SECURITY.md) identity/authorization; ADR-0002 | actor association, App installation, allow-list, live-target negative tests |
| TM-002 stale source/base tampering | ADR-0002 exact source/live-base binding | force-push, base movement, predecessor evidence, final head mismatch |
| TM-003 privileged PR workflow tampering | [TRD.md](TRD.md) event trust boundary; ADR-0008 | `pull_request_target` metadata-only and protected-dispatch contract tests |
| TM-004 repudiated evidence | typed evidence in [ERD.md](ERD.md) and authority trace below | producer/run/revision/command/consumer receipt completeness |
| TM-005 credential output disclosure | [SECURITY.md](SECURITY.md) publication boundary | stdout, stderr, service-log, timeout-tail, artifact redaction fixtures |
| TM-006 inherited secret disclosure | ADR-0004 and the secret registry | workflow secret union, absence, scope, fork, and prompt-leak tests |
| TM-007 provider/API denial of service | ADR-0003 and ADR-0007 | retry budget, provider exhaustion, exact-item deferral, other-lane progress |
| TM-008 stale cancellation/serialization | ADR-0001 plus executable Strix concurrency contract | competing run, same/different event class, current-head resolution |
| TM-009 advisory-to-authority elevation | ADR-0005 | self/bot/ineligible/stale review and ruleset rejection tests |
| TM-010 auditor/repair privilege escape | ADR-0001, ADR-0004, ADR-0008 | read-only audit and same-repository repair scope tests |
| TM-011 dependency/provenance compromise | [SECURITY.md](SECURITY.md) supply-chain controls | pin/hash/digest/SBOM/attestation mismatch fail-closed tests |
| TM-012 shell/path/output injection | strict schemas and sandbox/output sanitization | ref/path/YAML/shell/GitHub-output adversarial fixtures |
| TM-013 dispatch/receipt replay | ADR-0002 identity and idempotency | exact-key duplicate, altered-field, predecessor, completion replay tests |
| TM-014 synthetic/mis-typed evidence | [TRD.md](TRD.md) evidence taxonomy | absent/skipped/neutral/cancelled/similar-name/predecessor gate tests |

## Authority trace

| Claim | Authoritative object | Non-authoritative substitutes |
|---|---|---|
| check evidence | named GitHub check run bound to exact revision | comment text, unrelated status, predecessor run |
| status evidence | named commit-status context and producer | check with a similar display name |
| formal review evidence | eligible GitHub review object on current head | model verdict text, check conclusion, self/bot comment |
| merge authority | protected ruleset plus guarded GitHub merge transaction | approval prose, workflow success alone |
| release authority | release workflow/environment and its scoped actor | merged PR or review approval |
| operational closure | protected-main real-consumer run with target/run/revision identity | central source merge or synthetic fixture |

## Incident and change lineage

- `ContextualWisdomLab/.github#840` is the open exact dispatch-envelope and
  snapshot-only review-route change. Its behavior remains pending until merged
  and accepted from protected main.
- `ContextualWisdomLab/.github#842` is the open replacement for
  credential-shaped subprocess-log redaction. Closed, unmerged
  `ContextualWisdomLab/.github#841` is historical attempt evidence, not current
  implementation.
- `ContextualWisdomLab/.github#772` tracks the missing organization path for a
  counted independent non-author approval. Automation cannot self-satisfy it.
- `ContextualWisdomLab/.github#889` aligns external-head policy and runtime;
  `ContextualWisdomLab/.github#890` implements a shared writer lease;
  `ContextualWisdomLab/.github#891` makes Strix evidence fail closed;
  `ContextualWisdomLab/.github#892` aligns merge modes and mutation authority;
  `ContextualWisdomLab/.github#893` makes mention claims recoverable; and
  `ContextualWisdomLab/.github#894` makes material scheduler action failures
  terminally non-passing after the bounded queue scan.
- `ContextualWisdomLab/naruon#974` is merged product-planning evidence and
  informs the product-development lane; it does not prove this repository's
  operational controls.

## Standards alignment

| Contract area | Primary reference | Applied interpretation |
|---|---|---|
| secure development and provenance | NIST SP 800-218, Secure Software Development Framework | protect source/build integrity, review changes, preserve provenance, and respond to vulnerabilities |
| identity and least privilege | NIST SP 800-53 Rev. 5, AC/IA/AU/SC control families | job-scoped permission, attributable actors, audit records, protected transport |
| software supply chain | SLSA v1.2 specification and GitHub artifact-attestation guidance | verify subject digest, source/builder identity, immutable workflow revision, parameters, and verifier result; generation alone is not conformance |
| CI hardening | OpenSSF Scorecard and OWASP Top 10 CI/CD Security Risks | use heuristic checks as detective signals and model CI/CD trust/credential/artifact abuse cases, not as certification |
| GitHub event trust | GitHub secure-use, token, OIDC, organization-policy, and branch-protection documentation | full-SHA pins, restricted default permissions, conditional OIDC claims, protected workflow source, current final-revision approval |
| incident response | NIST SP 800-61 Rev. 3 | analyze root cause, restore verified integrity, close by explicit criteria, and feed lessons back into controls |
| evidence retention | NIST AU/CA controls and GitHub organization audit-log documentation | protect structured audit evidence and export required history before platform retention expires |

## References

GitHub. (n.d.). *About protected branches*. GitHub Docs. Retrieved August 9,
2026, from
https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *Artifact attestations*. GitHub Docs. Retrieved August 9, 2026,
from https://docs.github.com/en/actions/concepts/security/artifact-attestations

GitHub. (n.d.). *Disabling or limiting GitHub Actions for your organization*.
GitHub Docs. Retrieved August 9, 2026, from
https://docs.github.com/en/organizations/managing-organization-settings/disabling-or-limiting-github-actions-for-your-organization

GitHub. (n.d.). *OpenID Connect reference*. GitHub Docs. Retrieved August 9,
2026, from https://docs.github.com/en/actions/reference/security/oidc

GitHub. (n.d.). *Secure use reference*. GitHub Docs. Retrieved August 9, 2026,
from https://docs.github.com/en/actions/reference/security/secure-use

Joint Task Force. (2020). *Security and privacy controls for information
systems and organizations* (NIST Special Publication 800-53, Revision 5).
National Institute of Standards and Technology.
https://doi.org/10.6028/NIST.SP.800-53r5

Nelson, A., Rekhi, S., Souppaya, M., & Scarfone, K. (2025). *Incident response
recommendations and considerations for cybersecurity risk management: A CSF
2.0 community profile* (NIST Special Publication 800-61, Revision 3). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-61r3

Open Source Security Foundation. (n.d.). *OpenSSF Scorecard*. GitHub. Retrieved
August 9, 2026, from https://github.com/ossf/scorecard

OWASP Foundation. (n.d.). *OWASP Top 10 CI/CD security risks*. Retrieved August
9, 2026, from https://owasp.org/www-project-top-10-ci-cd-security-risks/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure Software Development
Framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218

Supply-chain Levels for Software Artifacts. (n.d.). *SLSA specification,
version 1.2*. Retrieved August 9, 2026, from https://slsa.dev/spec/v1.2/
