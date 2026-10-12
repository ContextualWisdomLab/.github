# Shared Strix PyJWT recursion security refresh

**Status:** Proposed on `ContextualWisdomLab/.github#2536`; hosted exact-head
revalidation and qualifying independent review remain mandatory.

## Failure scene and causal owner

Exact-head Security Scan run
[`36740858208`](https://github.com/ContextualWisdomLab/.github/actions/runs/36740858208),
job `109974634074`, evaluated
`d76ab4238591cc33b329881782e2759f3f5d51be`. Its dependency-review support
check reached GitHub successfully and the other scanner jobs passed. The
dependency-review action then rejected `requirements-strix-ci.txt` because
PyJWT 2.14.0 is affected by GHSA-42vr-xj54-vc7v, an unauthenticated
`RecursionError` denial of service in pre-verification payload parsing.

This is a shared Strix CI-runtime lock, so the central `.github` security and
review bounded context is the causal owner. It is not a transient network
failure, a consumer defect, or stale predecessor evidence. The dependency
review remains fail-closed; no severity threshold or workflow gate changes.

## RED to repair

The retained `test_strix_pyjwt_security_pin_is_an_explicit_lock_input`
contract first failed with one failure and four passing dependency tests when
it required PyJWT 2.15.1 but both the source and lock still selected 2.14.0.
The repair advances the explicit source pin and its two PyPI artifact hashes to
2.15.1. PyJWT's upstream changelog records the recursion hardening in 2.15.0;
the signed 2.15.1 release includes that fix and adds a Base64URL-padding
correction.

The focused dependency contract passes five tests after the repair. pip-audit
2.10.1's strict exact-pin audit reports no known vulnerabilities. The final
local tree passes 5,236 tests, 5 optional skips, and 40 subtests in the
warnings-as-errors repository suite; Ruff and `git diff --check` also pass.
Completion still requires fresh hosted Security Scan, Python Security, and
every other applicable exact-head check plus an independent review.

## References

PyJWT maintainers. (2026, September 28). *PyJWT 2.15.1* [Software release].
GitHub. https://github.com/jpadilla/pyjwt/releases/tag/2.15.1

PyJWT maintainers. (2026). *Changelog* [Software documentation]. GitHub.
https://github.com/jpadilla/pyjwt/blob/2.15.1/CHANGELOG.rst

Python Package Index. (2026, September 28). *PyJWT 2.15.1* [Package release].
https://pypi.org/project/PyJWT/2.15.1/
