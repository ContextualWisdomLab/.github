# OSV-Scanner Action single-version boundary

## Incident boundary

The central dependency scans invoke `google/osv-scanner-action` six times:
four scanner steps, their reporter gate, and the reusable pull-request scan.
All six remained on Action v2.3.8, while the stale dependency pull request
targeted v2.5.0 after v2.5.1 had become the current official release.

## Decision

Pin every central scanner, reporter, and reusable workflow use to
`6e4298ebc4db23e847df9b2e2de2939d6f066c67`, the commit referenced by the
official v2.5.1 tag. That release preserves package namespaces, restores the
local database cache environment variable, and fixes offline vulnerability
matching (Google, 2026).

GitHub documents that a full commit SHA is unique and immutable and should be
verified against the action repository (GitHub, n.d.). A repository-wide
contract therefore parses every central workflow occurrence, checks the exact
component inventory, rejects malformed pins or mismatched comments, and admits
only the reviewed v2.5.1 SHA and tag. Scan arguments, timeouts, permissions,
exact-base/head comparison, reporter gates, and fail-closed dependency policy
are unchanged.

## References

GitHub. (n.d.). *Using pre-written building blocks in your workflow*.
Retrieved August 24, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions

Google. (2026, August 17). *OSV-Scanner Action v2.5.1* [Software release].
https://github.com/google/osv-scanner-action/releases/tag/v2.5.1
