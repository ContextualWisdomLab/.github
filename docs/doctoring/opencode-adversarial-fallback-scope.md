# OpenCode adversarial fallback scope

## Incident boundary

The central OpenCode fallback allowlist omitted `adversarial_evidence.py` and
its contract test after the gate was extracted from an already-allowlisted
review helper. A pull request that changed the extracted trust-boundary code
therefore lost the bounded central review-process fallback solely because of
the refactor.

## Decision

Treat the extracted gate and its test as the same review-process unit as the
normalizer and approval gate by adding their exact repository paths to
`fallback_changed_file_allowed`. The existing
`fallback_changed_file_counts_as_core` function already classifies every
allowlisted central path except `.jules/bolt.md` as core, so no new classifier,
provider rule, credential, or approval path is needed.

This keeps the changed control and its regression evidence inside one
assessment scope. NIST SP 800-53 Rev. 5, control SA-11, requires ongoing unit,
integration, system, or regression evaluation and evidence at the defined
depth and coverage (National Institute of Standards and Technology, 2020).
The stable OWASP Web Security Testing Guide likewise includes positive and
negative security-control requirements in the security test suite (OWASP
Foundation, 2020).

## Verification

`tests/test_opencode_agent_contract.py` pins both exact paths in the workflow.
The allowlist stays closed: unrelated files remain ineligible, and every merge
still requires the existing exact-head checks and independent review policy.
The Strix quick-gate self-test names the current-attempt coverage artifact
download step, so a coverage-artifact hardening rename cannot silently leave
the protected workflow contract stale.

## References

National Institute of Standards and Technology. (2020). *Security and privacy
controls for information systems and organizations* (NIST Special Publication
800-53, Revision 5). https://doi.org/10.6028/NIST.SP.800-53r5

OWASP Foundation. (2020). *OWASP web security testing guide* (Version 4.2).
https://owasp.org/www-project-web-security-testing-guide/v42/
