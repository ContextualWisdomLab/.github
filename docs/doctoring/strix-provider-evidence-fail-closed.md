# Strix provider failures are incomplete evidence

## Incident

The trusted Strix workflow previously converted a non-zero gate result into a
successful required check when the console contained a provider-unavailable
marker and no parsed vulnerability line. That made a rate limit, provider
retirement response, or missing report indistinguishable from a completed
zero-finding scan.

The failure was observed on the same-head scan for
`ContextualWisdomLab/fast-mlsirm#816` at
`e2480e76dfa2139ab23f8372013681dd2cead46a`: the report artifact said zero
vulnerabilities, while the gate logs recorded NVIDIA NIM `429`, GitHub Models
`410`, and an explicit incomplete-evidence/fail-closed result. The required
check nevertheless reported success because the workflow wrapper neutralized
the non-zero gate exit.

## Decision

The trusted gate remains responsible for bounded retry and fallback. The
workflow wrapper now propagates every non-zero gate result. Provider outages,
timeouts, missing reports, and malformed evidence therefore remain failed
security checks until a clean, current-head scan is available. A successful
check is reserved for a trusted gate exit of zero that did not also print
fail-closed or incomplete-evidence text.

CWE-754 (MITRE, 2026) and IEEE 1028 (IEEE, 2008): a zero process exit is
an unusual condition when the same log says the scan is failing closed.
The wrapper must not treat that as a completed security review.

This preserves the security boundary: infrastructure failure may delay a merge,
but it cannot create an unaudited approval signal.

## References

MITRE. (2026). *CWE-754: Improper check for unusual or exceptional
conditions*. https://cwe.mitre.org/data/definitions/754.html

IEEE. (2008). *IEEE standard for software reviews and audits* (IEEE Std
1028-2008). https://doi.org/10.1109/IEEESTD.2008.4601584
