### Approval reuse requires a unique passing coverage decision

- OpenCode's existing exact-head approval path, merge-scheduler reuse gate, and
  repository-dispatch status publisher now inspect the coverage evidence
  summary as well as the coverage job conclusion. They accept exactly one
  `- Result: PASS` line and fail closed for missing, `NOT MEASURED`, non-passing,
  or duplicate decisions. A successful advisory coverage job therefore cannot
  reuse a predecessor approval when the current dispatch did not measure and
  pass coverage.
- The existing-approval CLI regression executes the non-passing decision branch
  directly, preserving the repository's 100% statement/branch coverage gate
  instead of excluding or suppressing the new fail-closed path.
- Existing approval reuse now evaluates the latest exact-head OpenCode
  publication decision instead of skipping a newer `CHANGES_REQUESTED` or
  otherwise invalid decision and resurrecting an older `APPROVED` review.
- The canonical Noema document-reader lock now selects `fast-uri` 3.1.8 and
  `ip-address` 10.7.2, removing CVE-2026-86472, CVE-2026-101911, and
  CVE-2026-101912 from the exact runtime installed by the hosted review lane.
  The bundle contract pins both transitive security versions so a later lock
  regeneration cannot silently restore the vulnerable releases.
- The central Strix input and generated hash lock now select LiteLLM 1.94.3,
  the patched 1.94 release for CVE-2026-84377. This closes the authenticated
  provider-credential forwarding and SSRF boundary exposed by 1.94.1 while
  preserving the existing Strix package and override set.
