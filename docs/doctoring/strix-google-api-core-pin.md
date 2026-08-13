# Strix google-api-core hash pin

## Incident and buyer impact

Dependabot rewrote `requirements-strix-ci-hashes.txt` from
`google-api-core==2.33.0` to `2.34.0`. Strix installs that lock with
`pip install --require-hashes`. A version line without the published
SHA-256 digests, or a leftover 2.33.0 pin, would either fail closed or
install an unreviewed wheel.

## Decision

Keep `google-api-core==2.34.0` with both published SHA-256 digests.
`google-api-core` is Apache-2.0 (permissive SPDX). Do not hand-edit the
hashes file later: regenerate from `requirements-strix-ci.txt` with the
header compile command.

CWE-494 forbids downloading code without integrity check (MITRE, 2026).
CWE-829 forbids including functionality from an untrusted control sphere.

## References

MITRE. (2026). *CWE-494: Download of code without integrity check*.
https://cwe.mitre.org/data/definitions/494.html

MITRE. (2026). *CWE-829: Inclusion of functionality from untrusted
control sphere*. https://cwe.mitre.org/data/definitions/829.html

Google LLC. (n.d.). *google-api-core*. PyPI. Retrieved August 13, 2026,
from https://pypi.org/project/google-api-core/2.34.0/
