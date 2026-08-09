# Automation control-plane traceability

Status: active_pr

## Implementation map

| Requirement or decision | Protected-main / authority surface | Verification surface | Status |
|---|---|---|---|
| Central reusable review contract | `.github/workflows/opencode-review.yml` | workflow contract and exact-head security tests | implemented_on_protected_main |
| Review dispatch and consumer evidence | `.github/workflows/opencode-review-dispatch.yml` | dispatch-envelope, OIDC, concurrency and protected-main canaries | implemented_on_protected_main |
| Merge/reviewer authority separation | `.github/workflows/pr-review-merge-scheduler.yml` | scheduler unit/contracts plus counted review evidence | implemented_on_protected_main |
| Ref-safe automated maintenance | `.github/workflows/pr-auto-rebase.yml` | stale-head, label and non-force update tests | implemented_on_protected_main |
| Canonical documentation graph | `docs/automation/**` | `tests/test_automation_documentation.py` | active_pr |
| Documentation fitness audit | `docs/automation/DOCUMENTATION_AUDIT.md` | required-doc/index/status/continuation contract | active_pr |
| Writer lease and work-conserving queue | ADR-0001 and ADR-0003 | external scheduler state + runtime queue/branch-head CAS behavior | accepted_architecture |
| Same-invocation continuation and conversation/documentation handoff | ADR-0010, PRD/TRD/Architecture/UML/Data Model | external prompt/configuration plus runtime lane-rotation evidence and documentation fitness | active_pr |
| External orchestration vs GitHub execution/evidence authority | Architecture/TRD/Data Model | documentation contract plus future runtime acceptance | accepted_architecture |
| Trusted bootstrap retry classes | ADR-0005 | transient/permanent classification tests and consumer replay | active_pr |
| Explicit secret interfaces | ADR-0006 | workflow/static contracts and secret-shaped negative tests | active_pr |
| Independent review governance | ADR-0007 and issue #772 | GitHub formal review plus exact-head eligibility tests | accepted_architecture |
| Protected-main closure | ADR-0008 | scheduled/manual consumer receipt, negative control and rollback | accepted_architecture |
| Central versus leaf ownership | ADR-0009 | reusable-workflow callers, source-repository tests, and documentation handoff audit | accepted_architecture |
| Product-specific PRD/TRD/ADR/UML/ERD | owning leaf repositories | repository-specific documentation fitness under each writer lease | planned |

## Authority boundaries

External scheduled agent/orchestrator configuration can establish invocation cadence and writer-lease ownership, but it does not substitute for GitHub source, check, status, review, merge, or protected-main runtime evidence. GitHub-native evidence does not by itself prove that an external work-conserving loop continued after an intermediate event. The canonical documentation graph records both authorities and their handoff without collapsing them.

Conversation history, prompt text, PR bodies, incident comments, and downloadable planning artifacts are candidate evidence. A durable shared decision becomes canonical only after live implementation/ownership is refetched and the existing documentation line is updated with the controlled maturity state. Product-specific decisions are handed to the owning product repository instead of being duplicated centrally.

## Incident linkage

Current incidents and active pull requests remain dated evidence, not shipped claims. Their exact SHAs and run identifiers belong in the issue/PR record. This matrix changes to `implemented_on_protected_main` only after protected integration and, for operational defects, real consumer acceptance.

A premature-termination incident remains open until the authoritative external continuation policy is corrected **and** runtime evidence proves that a blocked/intermediate lane rotates to another safe executable lane before a valid double-exit termination. A prompt diff or documentation update alone is not operational closure.

## Primary references

GitHub. (n.d.). *About protected branches*. https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *Reusing workflow configurations*. https://docs.github.com/actions/using-workflows/reusing-workflows

National Institute of Standards and Technology. (2022). *Secure Software Development Framework (SSDF) version 1.1* (SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

Open Source Security Foundation. (2025). *SLSA specification, version 1.1*. https://slsa.dev/spec/v1.1/
