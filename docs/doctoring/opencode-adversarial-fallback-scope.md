# OpenCode adversarial gate in fallback scope

## Incident boundary

The central OpenCode fallback allowlist treated extracted review helpers as
core files that cannot use the reduced fallback path. `adversarial_evidence.py`
and its contract test were omitted after the gate was extracted from the
model-pool runner. A change to that gate could therefore take the fallback
path and skip the adversarial evidence check that the review contract
requires.

## Decision

Materialize accepts only exact SHA-256 pins or a bounded relative `-r` include; a lone `--require-hashes` line is not lock evidence.

Add the extracted gate and its test to `fallback_changed_file_allowed` next
to the other central review helpers. NIST SP 800-53 Rev. 5 SA-11 requires
developer testing and evaluation to stay in the same assurance boundary as
the component under review (National Institute of Standards and Technology,
2020). OWASP similarly treats adversarial or negative testing as part of
the verification set, not as optional follow-up (OWASP Foundation, 2020).
Leaving the gate outside fallback scope would let a change to adversarial
evidence take a path that does not re-run that evaluation.

The allowlist remains an exact `owner/repo:path` membership test. It does
not broaden fallback, change model keys, or weaken `edit: deny`.

## References

National Institute of Standards and Technology. (2020). *Security and
privacy controls for information systems and organizations* (NIST SP
800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

OWASP Foundation. (2020). *OWASP testing guide v4.2*.
https://owasp.org/www-project-web-security-testing-guide/
