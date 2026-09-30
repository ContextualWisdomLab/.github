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
