# Shared Strix LiteLLM credential-exfiltration RCA

## Incident binding

On 2026-10-01, `.github` PR #2531 exact head
`516471fbe7d4e93a50c7bbba20402447f06f8d8b` failed Python Security run
`36799069276`, job `110169140365`. The unmodified
`requirements-strix-ci-hashes.txt` selected LiteLLM 1.94.1, and `pip-audit`
reported CVE-2026-84377 / GHSA-3cv6-jpf6-8222. The advisory describes an
authenticated request-body routing override that can redirect an upstream call,
exfiltrate configured provider credentials, and reach internal services.

This is a canonical control-plane dependency defect, not a product-PR finding
and not an audit-service transient. The same exact head also failed Trivy on the
Noema document reader's `fast-uri` 3.1.7 and `ip-address` 10.7.0. Stacked PR
#2545 already owns and proves the minimal Node transitive repair, so its ordinary
commit is preserved in the repaired #2531 ancestry instead of being copied or
reimplemented.

## Test-first repair

The RED contract
`test_strix_litellm_security_pin_is_an_explicit_lock_input` first failed because
the source input did not own a LiteLLM pin. The minimal repair:

1. selects `litellm==1.94.3` in `requirements-strix-ci.txt`, the first patched
   release in the retained 1.94 line;
2. regenerates `requirements-strix-ci-hashes.txt` with the repository's declared
   `uv pip compile --generate-hashes` command;
3. requires exact source/lock parity so a future resolver run cannot silently
   restore an affected release; and
4. preserves #2545's `fast-uri==3.1.8` and `ip-address==10.7.1` source overrides,
   lock, and nested-copy regression contract as unchanged ancestry.

No scanner finding is ignored or suppressed. `pip-audit` over the repaired
hash lock reports no known vulnerabilities. Hosted Security Scan, Python
Security, CodeQL, SAST, independent review, and ordinary protected merge remain
required; local evidence is not merge authorization.

## References

BerriAI. (2026, August 26). *Authenticated SSRF and provider-credential
exfiltration via unvalidated request-body routing parameters*
(GHSA-3cv6-jpf6-8222) [Security advisory]. GitHub.
https://github.com/BerriAI/litellm/security/advisories/GHSA-3cv6-jpf6-8222

National Institute of Standards and Technology. (2026). *CVE-2026-84377*.
National Vulnerability Database.
https://nvd.nist.gov/vuln/detail/CVE-2026-84377
