# Shared Python CI urllib3 2.8.0 security refresh

**Status:** Proposed on `ContextualWisdomLab/.github#2536`; hosted exact-head
revalidation and qualifying independent review remain mandatory.

## Failure scene and causal owner

After `ContextualWisdomLab/.github#2536` became Ready, exact-head Python
Security run
[`36737059681`](https://github.com/ContextualWisdomLab/.github/actions/runs/36737059681),
job `109961499214`, audited the pull-request merge revision whose head was
`88143f95d36be9b08550b52b86bd2baeefa0fe86`. The job found urllib3 2.7.0 in
both `requirements-pip-audit-ci-hashes.txt` and
`requirements-strix-ci-hashes.txt`. pip-audit reported CVE-2026-97687,
CVE-2026-97688, and CVE-2026-97689, each fixed in 2.8.0. The first can apply
target TLS policy or credentials to an HTTPS proxy; the latter two permit CPU
or memory denial of service through hostile chunked streaming responses.

These are shared `.github` CI-runtime locks, so the central security/review
bounded context is the causal owner. No product repository may suppress the
audit or copy a mutable proposed lock.

## RED to repair

The retained regression
`test_python_security_inputs_pin_patched_urllib3` first failed because neither
source input constrained urllib3. The repair adds the exact `urllib3==2.8.0`
constraint to both source inputs, regenerates both locks with their recorded
`uv pip compile --generate-hashes` commands, and requires source/lock parity in
both runtime graphs. The generated artifact hashes are
`0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3`
and `63bf2ead4c879426ebf22ef2a781eeb4aa3b4ae798a0435506f8687fd5bb9b63`.

The change does not alter pip-audit severity, failure classification, network
policy, or any workflow gate. Both regenerated locks returned `No known
vulnerabilities found` under pip-audit 2.10.1's strict exact-pin audit. The
focused dependency contract passes 5 tests, and the exact local tree passes
5,236 tests with 5 optional skips and 40 subtests while warnings are errors.
`git diff --check` passes. Completion still requires a fresh exact-head Python
Security result plus all other applicable checks and independent review.

## References

urllib3 maintainers. (2026, September 15). *urllib3 2.8.0* [Software
release]. GitHub. https://github.com/urllib3/urllib3/releases/tag/2.8.0

urllib3 maintainers. (2026, September 15). *Security advisories* [Security
advisory index]. GitHub. https://github.com/urllib3/urllib3/security/advisories
