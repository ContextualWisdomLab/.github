# Bounded control-plane SLI receipts

## Decision

`scripts/ci/control_plane_sli_receipt.py` builds one canonical
`cwl.control-plane-sli/v1` receipt from a local, finite-cardinality evidence
document. The builder does not query GitHub, interpret reviews, or acquire
mutation authority. Unknown fields, duplicate JSON members, non-finite
numbers, unbounded arrays, impossible recovery counts, follow-through that
exceeds intermediate events, exhausted retries with zero attempts, and
out-of-order or future timestamps fail closed.

Receipts are operator evidence: they tell a buyer whether the org control
plane is executable now, deferred for a named wait reason, or carrying
operational-acceptance debt. They are not merge authority.

To emit a receipt, write one finite local evidence JSON, then run
`python scripts/ci/control_plane_sli_receipt.py --input evidence.json --now
<UTC-Z>`. If the command raises `ValueError`, repair the evidence document.
Do not treat a printed receipt as merge permission.

## Why the boundary exists

A commercial operator cannot see queue health from GitHub check rollups
alone. Waiting on review or Checks is not a coding stop, but the wait must
be named and aged. An unbounded or authority-bearing collector would turn
that observability surface into a second control plane.

CWE-807 (reliance on untrusted inputs in a security decision) is the
rejection reason for treating a receipt as merge or writer authority
(MITRE, 2026). Timestamps are canonical whole-second UTC RFC 3339 values
ending in `Z` (Internet Engineering Task Force, 2002). Service-level
indicators remain descriptive measurements of named wait and recovery
classes, not control-plane commands (Beyer et al., 2016; International
Organization for Standardization, 2023).

## Trust-boundary sequence

```mermaid
flowchart LR
  A["Local finite evidence JSON"] --> B["Strict load: no NaN, no duplicate keys"]
  B --> C["Field, regex, and cardinality guards"]
  C --> D["Age, retry, transition, redirection aggregates"]
  D --> E["Canonical cwl.control-plane-sli/v1 JSON"]
```

Each arrow is fail-closed. A later stage does not repair an earlier
rejection.

## Verification contract

`tests/test_control_plane_sli_receipt.py` exercises a two-repository fixture,
strict JSON boundaries, impossible premature-stop recovery counts,
follow-through that exceeds intermediate events, exhausted retries with
zero attempts, and timestamp canonicalization.
`tests/test_control_plane_sli_receipt_quality_workflow_contract.py` pins the
exact-head quality workflow to every receipt surface, including ADR files.
The permanent quality workflow runs that suite with 100% branch coverage,
interrogate, compileall, and the full central test suite on the exact
pull-request head.

## References

Beyer, B., Jones, C., Petoff, J., & Murphy, N. R. (Eds.). (2016). *Site
reliability engineering: How Google runs production systems*. O'Reilly
Media. https://sre.google/sre-book/service-level-objectives/

International Organization for Standardization. (2023). *Systems and
software engineering — Systems and software Quality Requirements and
Evaluation (SQuaRE) — Product quality model* (ISO/IEC 25010:2023).
https://www.iso.org/standard/78176.html

Internet Engineering Task Force. (2002). *Date and time on the Internet:
Timestamps* (RFC 3339). https://www.rfc-editor.org/rfc/rfc3339

MITRE. (2026). *CWE-807: Reliance on untrusted inputs in a security
decision*. https://cwe.mitre.org/data/definitions/807.html
