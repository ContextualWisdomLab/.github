# Automation control-plane traceability

Status: active_pr

## Implementation map

| Requirement or decision | Protected-main implementation surface | Verification surface | Status |
|---|---|---|---|
| Central reusable review contract | `.github/workflows/opencode-review.yml` | workflow contract and exact-head security tests | implemented_on_protected_main |
| Review dispatch and consumer evidence | `.github/workflows/opencode-review-dispatch.yml` | dispatch-envelope, OIDC, concurrency and protected-main canaries | implemented_on_protected_main |
| Merge/reviewer authority separation | `.github/workflows/pr-review-merge-scheduler.yml` | scheduler unit/contracts plus counted review evidence | implemented_on_protected_main |
| Ref-safe automated maintenance | `.github/workflows/pr-auto-rebase.yml` | stale-head, label and non-force update tests | implemented_on_protected_main |
| Canonical documentation graph | `docs/automation/**` | `tests/test_automation_documentation.py` | active_pr |
| Writer lease and work-conserving queue | ADR-0001 and ADR-0003 | automation runtime contract and branch-head CAS behavior | accepted_architecture |
| Trusted bootstrap retry classes | ADR-0005 | transient/permanent classification tests and consumer replay | active_pr |
| Explicit secret interfaces | ADR-0006 | workflow/static contracts and secret-shaped negative tests | active_pr |
| Independent review governance | ADR-0007 and issue #772 | GitHub formal review plus exact-head eligibility tests | accepted_architecture |
| Protected-main closure | ADR-0008 | scheduled/manual consumer receipt, negative control and rollback | accepted_architecture |
| Central versus leaf ownership | ADR-0009 | reusable-workflow callers and source-repository tests | accepted_architecture |

## Incident linkage

Current incidents and active pull requests remain dated evidence, not shipped claims. Their exact SHAs and run identifiers belong in the issue/PR record. This matrix changes to `implemented_on_protected_main` only after protected integration and, for operational defects, real consumer acceptance.

## Primary references

GitHub. (n.d.). *About protected branches*. https://docs.github.com/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches

GitHub. (n.d.). *Reusing workflow configurations*. https://docs.github.com/actions/using-workflows/reusing-workflows

National Institute of Standards and Technology. (2022). *Secure Software Development Framework (SSDF) version 1.1* (SP 800-218). https://doi.org/10.6028/NIST.SP.800-218

Open Source Security Foundation. (2025). *SLSA specification, version 1.1*. https://slsa.dev/spec/v1.1/
