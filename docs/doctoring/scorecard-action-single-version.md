# Scorecard Action single-version boundary

## Incident boundary

The central pull-request, scheduled, and combined security workflows all use
OpenSSF Scorecard, but dependency automation updates workflow references
independently. A partial bump can leave posture evidence produced by different
action releases even though the jobs appear to provide one control.

## Decision

Pin every central `ossf/scorecard-action` use to
`2d1146689b8cda280b9bc96326124645441f03bc`, the commit referenced by the
official signed v2.4.4 tag. The current release updates Scorecard to v5.5.0 and
records POST failures without failing the entire action (Open Source Security
Foundation, 2026).

GitHub documents that a full commit SHA is unique and immutable and should be
verified against the action repository (GitHub, n.d.). A repository-wide
contract therefore parses every central workflow occurrence, rejects malformed
pins, and admits only the reviewed v2.4.4 SHA and tag. Workflow permissions,
events, arguments, SARIF semantics, thresholds, and fail-closed gates are
unchanged.

## References

GitHub. (n.d.). *Using pre-written building blocks in your workflow*.
Retrieved August 24, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/find-and-customize-actions

Open Source Security Foundation. (2026, July 23). *Scorecard Action v2.4.4*
[Software release].
https://github.com/ossf/scorecard-action/releases/tag/v2.4.4
