# Product gap baseline source-integrity repair

## Incident

Repository Metadata Reconcile run `36777030872`, job `110097412873`, ran
against `.github#2530@61a3f2ebbf6adf9c237a647552ccffeb52b00f47`.
Five tests failed because `docs/product-technical-gap-baseline.md` began with
a connector display warning and contained only 433 lines. The previous complete
artifact contained 3,703 lines and 361,021 bytes.

## Root cause

Commit `bd3cfe8645844ec7b140a1b73d2b339f8e4283dc` attempted to change one
dependency-floor row, but persisted a truncated connector rendering instead of
the Git blob. This removed G-17 publication evidence, the 107-row live
inventory, APA 7th references, and buyer-facing PRD/TRD/UML/Gap evidence.

## RED to GREEN

- RED `c8d41f52962814d080a1c4947acbff2f3f9bb81e` rejects the connector warning
  and output-line banner at the artifact boundary.
- GREEN restores the complete parent blob and reapplies only the intended
  `ip-address` 10.7.1 dependency-floor row.
- The focused integrity, gap-baseline, and published-lineage tests must pass
  before the full warnings-fatal repository suite is accepted.

Hosted exact-head Metadata, authenticated agent verdicts, and independent
approval remain required; this record is not merge authorization.
