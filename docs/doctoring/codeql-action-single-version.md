# CodeQL Action single-version boundary

## Incident boundary

The central security workflows referenced three CodeQL Action releases:
v4.37.0 for pull-request analysis, v4.37.5 for scheduled analysis, and v4.37.4
for most SARIF uploads. The open v4.37.6 alignment (#918) predated the official
v4.37.7 release, while the v4.37.7 dependency update (#1107) covered only the
two workflows containing `init` and `analyze` steps. Five upload-only workflows
would therefore have remained on a different reviewed artifact.

## Decision

Pin every central `github/codeql-action/{init,analyze,upload-sarif}` use to
`ff2f1c621b7f889edc0d3c761ac2e6a3f8cdb0dd`, the commit referenced by the
official annotated v4.37.7 tag. GitHub documents that a full commit SHA is
unique and immutable and must be verified against the action repository
(GitHub, n.d.). The v4.37.7 release updates the default CodeQL bundle to
v2.26.3 (GitHub, 2026).

The change does not alter workflow permissions, event triggers, SARIF paths,
finding thresholds, or fail-closed gates. A repository-wide contract parses
every central workflow occurrence, rejects malformed pins, requires all three
CodeQL Action entry points, and admits only the reviewed SHA and release tag.

## References

GitHub. (2026, August 13). *CodeQL Action v4.37.7* [Software release].
https://github.com/github/codeql-action/releases/tag/v4.37.7

GitHub. (n.d.). *Using pre-written building blocks in your workflow*.
Retrieved August 24, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions
